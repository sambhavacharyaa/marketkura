"""Business rules shared by the HTML views and the REST API."""

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext as _

from .models import Category, Comment, CommentVote, Notification, Post, PostTag, PostVote, Report, Tag, User

MAX_COMMENT_DEPTH = 5
MAX_TAGS_PER_POST = 5


class PostingBlocked(Exception):
    """Raised when a member is not currently allowed to post or comment."""


class ReportError(Exception):
    """Raised when a report cannot be filed (own content, duplicate)."""


# --- Request helpers --------------------------------------------------------

def client_ip(request):
    if settings.USE_X_FORWARDED_FOR:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def safe_next_url(request, fallback):
    """Return the ?next= / POST next value only when it points back at this site."""
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


# --- Rate limiting -----------------------------------------------------------

def _cache_key(prefix, *parts):
    digest = hashlib.sha256('|'.join(str(part).lower() for part in parts).encode()).hexdigest()[:32]
    return f'mk:{prefix}:{digest}'


def register_hit(prefix, *parts, window):
    """Count one event for this key and return the running total inside the window."""
    key = _cache_key(prefix, *parts)
    cache.add(key, 0, window)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        return 1


def current_hits(prefix, *parts):
    return cache.get(_cache_key(prefix, *parts), 0)


def login_locked(request, username):
    ip = client_ip(request)
    return (current_hits('login', ip, username) >= settings.LOGIN_MAX_FAILURES
            or current_hits('login-ip', ip) >= settings.LOGIN_MAX_FAILURES * 4)


def record_login_failure(request, username):
    ip = client_ip(request)
    register_hit('login', ip, username, window=settings.LOGIN_LOCKOUT_SECONDS)
    register_hit('login-ip', ip, window=settings.LOGIN_LOCKOUT_SECONDS)


def clear_login_failures(request, username):
    cache.delete(_cache_key('login', client_ip(request), username))


def signup_limited(request):
    return register_hit('signup', client_ip(request), window=3600) > settings.SIGNUP_MAX_PER_HOUR


def contact_limited(request):
    return register_hit('contact', client_ip(request), window=3600) > settings.CONTACT_MAX_PER_HOUR


TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'


def turnstile_passes(request):
    """True when Turnstile isn't configured (local dev with no keys set) or the submitted token
    verifies with Cloudflare. False — never raises — on a missing/invalid token or a network or
    API failure, so a Cloudflare outage fails closed rather than letting spam through silently."""
    if not settings.TURNSTILE_SECRET_KEY:
        return True
    token = request.POST.get('cf-turnstile-response', '')
    if not token:
        return False
    data = urllib.parse.urlencode({
        'secret': settings.TURNSTILE_SECRET_KEY, 'response': token, 'remoteip': client_ip(request),
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TURNSTILE_VERIFY_URL, data=data), timeout=5) as resp:
            result = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
    return bool(result.get('success'))


# --- Visibility (removed content and shadow-bans) ---------------------------------

def visible_posts(user, queryset=None):
    posts = Post.objects.all() if queryset is None else queryset
    posts = posts.filter(is_removed=False)
    if user.is_authenticated and user.is_staff:
        return posts
    hidden = Q(user__is_shadow_banned=True)
    if user.is_authenticated:
        hidden &= ~Q(user=user)
    return posts.exclude(hidden)


def can_view_post(user, post):
    if user.is_authenticated and user.is_staff:
        return True
    if post.is_removed:
        return False
    return not post.user.is_shadow_banned or (user.is_authenticated and user == post.user)


def post_queryset(user):
    posts = Post.objects.select_related('user', 'category', 'asset').annotate(
        comment_count=Count('comments', filter=Q(comments__is_removed=False), distinct=True))
    return visible_posts(user, posts)


def posts_for_tag(user, tag):
    """Everything about a company/tag: posts where it is the asset or one of the tags."""
    return post_queryset(user).filter(Q(asset=tag) | Q(pk__in=PostTag.objects.filter(tag=tag).values('post_id')))


def trending_posts(user, days=7):
    """Score-ranked posts from the last `days`. Falls back to the most-upvoted posts from the
    last 30 days if that window has nothing, then to the latest posts overall — so the Trending
    tab is only ever empty when there are no posts at all, not just no recent ones."""
    since = timezone.now() - timedelta(days=days)
    posts = (post_queryset(user).filter(created_at__gte=since)
             .annotate(score=F('upvotes') + 2 * F('comment_count')).order_by('-score', '-created_at'))
    if posts.exists():
        return posts
    month_since = timezone.now() - timedelta(days=30)
    recent_upvoted = post_queryset(user).filter(created_at__gte=month_since).order_by('-upvotes', '-comment_count', '-created_at')
    if recent_upvoted.exists():
        return recent_upvoted
    return post_queryset(user).order_by('-created_at')


# --- Posting rules -------------------------------------------------------------

def has_unlock(user, feature):
    """Reputation-based feature unlocks (V2). Verified members and staff always qualify."""
    if not user.is_authenticated:
        return False
    if user.is_verified or user.is_staff:
        return True
    return user.karma_score >= settings.REPUTATION_UNLOCKS.get(feature, 0)


def check_can_post(user, category, post_type=Post.TYPE_DISCUSSION):
    if user.is_staff:
        return
    if category.requires_verified and not user.is_verified:
        raise PostingBlocked(_('Only verified members can start threads in %(name)s.') % {'name': category.display_name})
    if category.min_karma and not user.is_verified and user.karma_score < category.min_karma:
        raise PostingBlocked(_('You need %(karma)s reputation to start threads in %(name)s.') % {'karma': category.min_karma, 'name': category.display_name})
    if post_type == Post.TYPE_AMA and not user.is_verified:
        raise PostingBlocked(_('Only verified members can host an AMA.'))
    if user.is_new_account:
        since = timezone.now() - timedelta(days=1)
        if Post.objects.filter(user=user, created_at__gte=since).count() >= settings.NEW_ACCOUNT_POSTS_PER_DAY:
            raise PostingBlocked(_('New accounts can publish %(limit)s posts a day for their first %(days)s days. Please try again tomorrow.') % {
                'limit': settings.NEW_ACCOUNT_POSTS_PER_DAY, 'days': settings.NEW_ACCOUNT_DAYS})


def thread_closed_reason(user, post):
    """Why this member cannot add to the thread right now (locked, AMA over), or '' if it is open."""
    if user.is_authenticated and user.is_staff:
        return ''
    if post.is_locked:
        return _('This thread is locked.')
    if post.ama_state == 'ended' and user != post.user:
        return _('This AMA has ended and is no longer accepting questions.')
    return ''


def check_can_comment(user, post):
    closed = thread_closed_reason(user, post)
    if closed:
        raise PostingBlocked(closed)
    if user.is_new_account and not user.is_staff:
        since = timezone.now() - timedelta(days=1)
        if Comment.objects.filter(user=user, created_at__gte=since).count() >= settings.NEW_ACCOUNT_COMMENTS_PER_DAY:
            raise PostingBlocked(_('New accounts have a daily comment limit. Please try again tomorrow.'))


def publish_post(user, post, tag_names):
    """Apply posting rules, then save a new post with its company stub, tags and mentions."""
    check_can_post(user, post.category, post.type)
    post.user = user
    with transaction.atomic():
        asset_from_post(post)
        post.save()
        sync_post_tags(post, tag_names)
    notify_mentions(post.body, user, post)
    return post


def add_comment(user, post, body, parent=None):
    """Apply commenting rules, then save a comment and notify the people involved."""
    check_can_comment(user, post)
    comment = Comment.objects.create(post=post, user=user, parent_comment=parent, body=body)
    recipient = parent.user if parent else post.user
    if parent:
        message = _('%(user)s replied to your comment.') % {'user': user.username}
    else:
        message = _('%(user)s commented on your post.') % {'user': user.username}
    create_notification(recipient, user, 'reply' if parent else 'comment', message, post)
    notify_mentions(body, user, post)
    return comment


def file_report(user, category, reason, post=None, comment=None):
    target = comment or post
    if target.user == user:
        raise ReportError(_('You cannot report your own content.'))
    reason = (reason or '').strip() or dict(Report.CATEGORY_CHOICES)[category]
    try:
        with transaction.atomic():
            return Report.objects.create(post=None if comment else post, comment=comment, reporter=user, category=category, reason=reason)
    except IntegrityError:
        raise ReportError(_('You have already reported this.'))


# --- Assets and tags -------------------------------------------------------------

def asset_from_post(post):
    """Resolve the free-text ticker on a post to a Tag, creating the company stub if needed."""
    if not post.asset_id and (post.asset_tag or '').strip():
        ticker = post.asset_tag.strip().upper()
        post.asset = Tag.objects.filter(Q(ticker__iexact=ticker) | Q(slug__iexact=slugify(ticker, allow_unicode=True))).first()
        if not post.asset:
            post.asset = Tag.objects.create(ticker=ticker, name=ticker, slug=slugify(ticker, allow_unicode=True) or ticker.lower())


def parse_tag_names(raw):
    names = []
    for part in re.split(r'[,\n]', raw or ''):
        name = part.strip().lstrip('#').strip()
        if name and name.lower() not in {n.lower() for n in names}:
            names.append(name[:50])
    return names[:MAX_TAGS_PER_POST]


def sync_post_tags(post, names):
    tags = []
    for name in names:
        slug = slugify(name, allow_unicode=True)
        if not slug:
            continue
        tag = Tag.objects.filter(Q(slug=slug) | Q(ticker__iexact=name)).first()
        if not tag:
            tag = Tag.objects.create(name=name, slug=slug, is_company=False)
        tags.append(tag)
    PostTag.objects.filter(post=post).exclude(tag__in=tags).delete()
    for tag in tags:
        PostTag.objects.get_or_create(post=post, tag=tag)


# --- Notifications ---------------------------------------------------------------

def create_notification(recipient, actor, kind, message, target=None):
    if recipient == actor or (actor is not None and actor.is_shadow_banned):
        return
    Notification.objects.create(
        recipient=recipient, actor=actor, notification_type=kind, message=message,
        target_type=target.__class__.__name__.lower() if target else '', target_id=target.pk if target else None,
        target_url=target.get_absolute_url() if target and hasattr(target, 'get_absolute_url') else '')


MENTION_RE = re.compile(r'(?<![\w@])@([\w.-]{1,150})')


def notify_mentions(text, actor, target, limit=10):
    usernames = {match.rstrip('.-') for match in MENTION_RE.findall(text or '')} - {''}
    for username in sorted(usernames)[:limit]:
        recipient = User.objects.filter(username__iexact=username).first()
        if recipient:
            create_notification(recipient, actor, 'mention', _('%(user)s mentioned you.') % {'user': actor.username}, target)


# --- Votes and karma ---------------------------------------------------------

def recalculate_karma(user):
    """Karma is the number of upvotes a member's posts and comments received from others."""
    karma = (PostVote.objects.filter(post__user=user).exclude(user=user).count()
             + CommentVote.objects.filter(comment__user=user).exclude(user=user).count())
    if user.karma_score != karma:
        user.karma_score = karma
        user.save(update_fields=['karma_score'])
    return karma


def toggle_post_vote(user, post):
    """Flip the member's upvote on a post and return True if it is now voted."""
    vote, created = PostVote.objects.get_or_create(post=post, user=user)
    if not created:
        vote.delete()
    else:
        create_notification(post.user, user, 'reaction', _('%(user)s reacted to your post.') % {'user': user.username}, post)
    post.upvotes = post.votes.count()
    post.save(update_fields=['upvotes'])
    recalculate_karma(post.user)
    return created


def toggle_comment_vote(user, comment):
    vote, created = CommentVote.objects.get_or_create(comment=comment, user=user)
    if not created:
        vote.delete()
    comment.upvotes = comment.votes.count()
    comment.save(update_fields=['upvotes'])
    recalculate_karma(comment.user)
    return created


# --- Comment threads ---------------------------------------------------------------

def build_comment_tree(post, viewer):
    """Return top-level comments, each with .children (recursive), .depth and .user_voted set."""
    comments = list(post.comments.select_related('user'))
    can_see_hidden = viewer.is_authenticated and viewer.is_staff
    voted = set(CommentVote.objects.filter(user=viewer, comment__post=post).values_list('comment_id', flat=True)) if viewer.is_authenticated else set()
    by_parent = defaultdict(list)
    for comment in comments:
        hidden = comment.user.is_shadow_banned and not can_see_hidden and comment.user_id != getattr(viewer, 'pk', None)
        if hidden:
            continue
        comment.user_voted = comment.pk in voted
        by_parent[comment.parent_comment_id].append(comment)

    def attach(comment, depth):
        comment.depth = min(depth, MAX_COMMENT_DEPTH)
        comment.children = by_parent.get(comment.pk, [])
        for child in comment.children:
            attach(child, depth + 1)

    roots = by_parent.get(None, [])
    for root in roots:
        attach(root, 0)
    return roots


# --- Search ----------------------------------------------------------------------

def search_posts(posts, query):
    """Full-text search on PostgreSQL (ranked), substring search elsewhere.

    The substring branch is always included so partial tickers and Nepali text, which the
    default Postgres tokenizer can split badly, are still found. Matches on title, body, the
    post's primary asset (ticker/company name), its category (name or slug) and any topic tags
    (PostTag -> Tag) attached to it - a post filed under NEPSE with "NEPSE" nowhere in its own
    title/body previously wasn't found searching "NEPSE" at all.
    """
    contains = (Q(title__icontains=query) | Q(body__icontains=query) | Q(asset_tag__icontains=query)
                | Q(asset__ticker__icontains=query) | Q(asset__company_name__icontains=query)
                | Q(category__name__icontains=query) | Q(category__slug__icontains=query)
                | Q(tags__tag__name__icontains=query) | Q(tags__tag__slug__icontains=query))
    if connection.vendor != 'postgresql':
        # No Postgres ranking available here, but "title matches above body matches" still
        # needs to hold - a simple title-match flag, sorted first, gets that cheaply.
        title_match = Case(When(title__icontains=query, then=Value(1)), default=Value(0), output_field=IntegerField())
        return posts.filter(contains).distinct().annotate(title_match=title_match).order_by('-title_match', '-created_at')
    from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
    vector = (SearchVector('title', weight='A', config='simple') + SearchVector('asset__ticker', 'asset__company_name', weight='A', config='simple')
              + SearchVector('body', weight='B', config='simple'))
    search_query = SearchQuery(query, config='simple', search_type='websearch')
    return (posts.annotate(search=vector, rank=SearchRank(vector, search_query))
            .filter(Q(search=search_query) | contains).distinct().order_by('-rank', '-created_at'))


def search_tags(query):
    return Tag.objects.filter(Q(ticker__icontains=query) | Q(name__icontains=query) | Q(company_name__icontains=query)).order_by('ticker', 'name')


def search_categories(query):
    return Category.objects.filter(Q(name__icontains=query) | Q(slug__icontains=query)).order_by('name')


# --- Moderation helpers ----------------------------------------------------------------

def pump_watch():
    """Assets that suddenly attracted many posts from several authors (blueprint section 19)."""
    since = timezone.now() - timedelta(hours=settings.PUMP_WATCH_HOURS)
    return (Tag.objects.filter(asset_posts__created_at__gte=since, asset_posts__is_removed=False)
            .annotate(recent_posts=Count('asset_posts', distinct=True), recent_authors=Count('asset_posts__user', distinct=True))
            .filter(recent_posts__gte=settings.PUMP_WATCH_POSTS, recent_authors__gte=settings.PUMP_WATCH_AUTHORS)
            .order_by('-recent_posts'))


# --- Home page widgets ---------------------------------------------------------------

MIN_THESES_FOR_SENTIMENT = 3


def trending_companies(days=7, limit=8):
    """Companies with the most posts recently (public counts only, so shadow-banned authors are excluded)."""
    since = timezone.now() - timedelta(days=days)
    return list(Tag.objects.filter(is_company=True, asset_posts__created_at__gte=since, asset_posts__is_removed=False,
                                   asset_posts__user__is_shadow_banned=False)
                .annotate(recent_posts=Count('asset_posts', distinct=True)).order_by('-recent_posts', 'ticker')[:limit])


def thesis_sentiment(limit=5, minimum=MIN_THESES_FOR_SENTIMENT):
    """Long-vs-short split of self-reported theses per company. Shown only with enough theses to mean something."""
    rows = (Tag.objects.filter(is_company=True, asset_posts__type=Post.TYPE_THESIS, asset_posts__is_removed=False,
                               asset_posts__user__is_shadow_banned=False, asset_posts__position_type__in=('long', 'short'))
            .annotate(theses=Count('asset_posts', distinct=True),
                      longs=Count('asset_posts', filter=Q(asset_posts__position_type='long'), distinct=True))
            .filter(theses__gte=minimum).order_by('-theses', 'ticker')[:limit])
    result = []
    for tag in rows:
        tag.long_pct = round(100 * tag.longs / tag.theses)
        tag.short_pct = 100 - tag.long_pct
        result.append(tag)
    return result


def upcoming_amas(user, limit=3):
    """AMAs that are live or still to come, soonest first."""
    now = timezone.now()
    amas = visible_posts(user, Post.objects.filter(type=Post.TYPE_AMA).select_related('user'))
    return list(amas.filter(Q(ama_ends_at__isnull=True) | Q(ama_ends_at__gte=now)).order_by('ama_starts_at', '-created_at')[:limit])


def top_contributors(limit=5):
    """Members ranked by reputation (upvotes received). Deliberately not a performance ranking."""
    return list(User.objects.filter(is_shadow_banned=False, karma_score__gt=0).order_by('-karma_score', 'username')[:limit])


def platform_stats():
    """Real aggregate counts shown on the home page (never invented placeholder numbers)."""
    return {
        'posts': Post.objects.filter(is_removed=False, user__is_shadow_banned=False).count(),
        'members': User.objects.filter(is_shadow_banned=False).count(),
        'companies': Tag.objects.filter(is_company=True, asset_posts__is_removed=False, asset_posts__user__is_shadow_banned=False).distinct().count(),
    }
