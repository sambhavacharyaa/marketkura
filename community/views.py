import json
import re
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordResetView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import services
from .forms import (CommentForm, ContactForm, EmailAuthenticationForm, NewsForm, PostForm, ProfileForm, ReportForm,
                    SignUpForm, StartupForm, VerificationRequestForm, VerificationReviewForm, WatchlistForm)
from .models import (Category, CategoryFollow, Comment, Follow, NewsPost, Notification, Post, PostVote, Report,
                     StartupProfile, Tag, User, VerificationRequest, Watchlist, WatchlistItem)
from .services import PostingBlocked, post_queryset, safe_next_url
from .templatetags.community_extras import markdown_safe

SLUG_PK_RE = re.compile(r'(?:^|-)(\d+)$')


def staff_required(view):
    """Staff only: anonymous users go to login, signed-in non-staff get a 403."""
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def paginate(request, queryset, per_page=12):
    if not queryset.ordered:
        queryset = queryset.order_by('-created_at')
    page = Paginator(queryset, per_page).get_page(request.GET.get('page'))
    if queryset.model is Post:
        # One query tells every post card on the page whether this member already upvoted it.
        voted = set(PostVote.objects.filter(user=request.user, post__in=[p.pk for p in page]).values_list('post_id', flat=True)) if request.user.is_authenticated else set()
        for post in page:
            post.user_voted = post.pk in voted
    return page


def query_without_page(request):
    query = request.GET.copy()
    query.pop('page', None)
    return query.urlencode()


def apply_post_filters(request, posts):
    query = request.GET.get('q', '').strip()
    if query:
        posts = services.search_posts(posts, query)
    if request.GET.get('type') in dict(Post.POST_TYPES):
        posts = posts.filter(type=request.GET['type'])
    if request.GET.get('category'):
        posts = posts.filter(category__slug=request.GET['category'])
    if request.GET.get('asset'):
        posts = posts.filter(Q(asset__ticker__iexact=request.GET['asset']) | Q(asset__slug__iexact=request.GET['asset']))
    if request.GET.get('verified') == '1':
        posts = posts.filter(user__is_verified=True)
    if request.GET.get('position') in ('long', 'short', 'watching'):
        posts = posts.filter(position_type=request.GET['position'])
    if request.GET.get('horizon') in ('short', 'medium', 'long'):
        posts = posts.filter(time_horizon=request.GET['horizon'])
    if request.GET.get('date') == 'week':
        posts = posts.filter(created_at__gte=timezone.now() - timedelta(days=7))
    if request.GET.get('sort') == 'discussed':
        posts = posts.order_by('-comment_count', '-upvotes', '-created_at')
    return posts


def asset_choices():
    return Tag.objects.filter(is_company=True).order_by('ticker', 'name')


# --- Forum ----------------------------------------------------------------------------

def home(request):
    tab = request.GET.get('tab', 'latest')
    posts = post_queryset(request.user)
    if tab == 'following' and request.user.is_authenticated:
        followed_users = Follow.objects.filter(follower=request.user).values('following_id')
        followed_categories = CategoryFollow.objects.filter(user=request.user).values('category_id')
        posts = posts.filter(Q(user_id__in=followed_users) | Q(category_id__in=followed_categories))
    elif tab == 'trending':
        posts = services.trending_posts(request.user, days=30)
    else:
        tab = 'latest'
    query = request.GET.get('q', '').strip()
    followed = set(request.user.category_follows.values_list('category_id', flat=True)) if request.user.is_authenticated else set()
    return render(request, 'home.html', {
        'categories': Category.objects.all(), 'followed_categories': followed, 'tab': tab,
        'posts': paginate(request, apply_post_filters(request, posts)), 'query': query,
        'assets': asset_choices(), 'filter_query': query_without_page(request),
        'active_category': request.GET.get('category', ''),
        'trending_companies': services.trending_companies(),
        'thesis_sentiment': services.thesis_sentiment(),
        'upcoming_amas': services.upcoming_amas(request.user),
        'top_contributors': services.top_contributors(),
        'min_theses': services.MIN_THESES_FOR_SENTIMENT,
        'categories_all': Category.objects.all(),
        'stats': None if request.user.is_authenticated else services.platform_stats(),
    })


def posts(request):
    return render(request, 'posts.html', {
        'posts': paginate(request, apply_post_filters(request, post_queryset(request.user))),
        'assets': asset_choices(), 'filter_query': query_without_page(request),
    })


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    following = request.user.is_authenticated and CategoryFollow.objects.filter(user=request.user, category=category).exists()
    return render(request, 'category_detail.html', {
        'category': category, 'following': following,
        'posts': paginate(request, apply_post_filters(request, post_queryset(request.user).filter(category=category))),
        'filter_query': query_without_page(request),
    })


@login_required
@require_POST
def toggle_category_follow(request, slug):
    category = get_object_or_404(Category, slug=slug)
    follow, created = CategoryFollow.objects.get_or_create(user=request.user, category=category)
    if not created:
        follow.delete()
    return redirect(safe_next_url(request, category.get_absolute_url()))


def structured_data(request, post):
    """schema.org markup so search engines understand discussions and Q&A."""
    url = request.build_absolute_uri(post.get_absolute_url())
    author = {'@type': 'Person', 'name': post.user.username, 'url': request.build_absolute_uri(post.user.get_absolute_url())}
    comments = [c for c in post.comments.select_related('user') if not c.is_removed and not c.user.is_shadow_banned]
    if post.type == Post.TYPE_AMA:
        # The host's first reply to a question is exposed as the answer.
        answers = [c for c in comments if c.parent_comment_id and c.user_id == post.user_id]
        question = {'@type': 'Question', 'name': post.title, 'text': post.body[:500], 'answerCount': len(answers),
                    'dateCreated': post.created_at.isoformat(), 'author': author}
        if answers:
            question['acceptedAnswer'] = {'@type': 'Answer', 'text': answers[0].body[:500], 'author': author,
                                          'dateCreated': answers[0].created_at.isoformat(), 'url': url}
        data = {'@context': 'https://schema.org', '@type': 'QAPage', 'mainEntity': question}
    else:
        data = {'@context': 'https://schema.org', '@type': 'DiscussionForumPosting', 'headline': post.title, 'url': url,
                'text': post.body[:1000], 'datePublished': post.created_at.isoformat(), 'dateModified': post.updated_at.isoformat(),
                'author': author, 'commentCount': len(comments), 'interactionStatistic': {
                    '@type': 'InteractionCounter', 'interactionType': 'https://schema.org/LikeAction', 'userInteractionCount': post.upvotes}}
    return json.dumps(data).replace('<', '\\u003c')


def post_from_slug(slug):
    match = SLUG_PK_RE.search(slug)
    if not match:
        raise Http404
    return get_object_or_404(Post.objects.select_related('user', 'category', 'asset'), pk=int(match.group(1)))


def post_detail(request, slug):
    post = post_from_slug(slug)
    if not services.can_view_post(request.user, post):
        raise Http404
    if slug != post.url_slug:
        return redirect(post.get_absolute_url(), permanent=True)
    comments = services.build_comment_tree(post, request.user)
    user_voted = request.user.is_authenticated and post.votes.filter(user=request.user).exists()
    context = {
        'post': post, 'comments': comments, 'comment_form': CommentForm(), 'user_voted': user_voted,
        'comment_count': post.comments.filter(is_removed=False).count(),
        'tags': [pt.tag for pt in post.tags.select_related('tag')],
        'json_ld': structured_data(request, post),
        'canonical_url': request.build_absolute_uri(post.get_absolute_url()),
        'is_ama': post.type == Post.TYPE_AMA,
        'closed_reason': services.thread_closed_reason(request.user, post),
        'can_reply': not services.thread_closed_reason(request.user, post),
    }
    if post.type == Post.TYPE_AMA:
        answered = {c.parent_comment_id for c in post.comments.filter(user=post.user, parent_comment__isnull=False)}
        context['unanswered_count'] = len([c for c in comments if c.pk not in answered and c.user_id != post.user_id])
    return render(request, 'post_detail.html', context)


def blocked_form_response(request, form, exc, editing=False, post=None):
    form.add_error(None, str(exc))
    return render(request, 'post_form.html', {'form': form, 'editing': editing, 'post': post}, status=403)


@login_required
def create_post(request):
    initial = {key: request.GET[key] for key in ('category', 'type') if request.GET.get(key)}
    form = PostForm(request.POST or None, request.FILES or None, user=request.user, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            post = services.publish_post(request.user, form.save(commit=False), form.cleaned_data['tags'])
        except PostingBlocked as exc:
            return blocked_form_response(request, form, exc)
        messages.success(request, _('Your post is live. Posts are user-generated and theses are self-reported.'))
        return redirect(post.get_absolute_url())
    return render(request, 'post_form.html', {'form': form, 'editing': False})


@login_required
def edit_post(request, pk):
    post = get_object_or_404(Post, pk=pk, is_removed=False)
    if post.user != request.user:
        return HttpResponseForbidden(_('You can only edit your own posts.'))
    form = PostForm(request.POST or None, request.FILES or None, instance=post, user=request.user)
    if request.method == 'POST' and form.is_valid():
        post = form.save(commit=False)
        if 'category' in form.changed_data or 'type' in form.changed_data:
            try:
                services.check_can_post(request.user, post.category, post.type)
            except PostingBlocked as exc:
                return blocked_form_response(request, form, exc, editing=True, post=post)
        with transaction.atomic():
            services.asset_from_post(post)
            post.save()
            services.sync_post_tags(post, form.cleaned_data['tags'])
        return redirect(post.get_absolute_url())
    return render(request, 'post_form.html', {'form': form, 'editing': True, 'post': post})


@login_required
def delete_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if post.user != request.user:
        return HttpResponseForbidden(_('You can only delete your own posts.'))
    if request.method == 'POST':
        post.delete()
        services.recalculate_karma(request.user)
        return redirect('home')
    return render(request, 'confirm_delete.html', {'object': post, 'label': _('post')})


# --- Comments and votes ------------------------------------------------------------------

@login_required
@require_POST
def add_comment(request, pk):
    post = get_object_or_404(Post, pk=pk, is_removed=False)
    if not services.can_view_post(request.user, post):
        raise Http404
    form = CommentForm(request.POST)
    if not form.is_valid():
        messages.error(request, _('Please write something before posting.'))
        return redirect(post.get_absolute_url())
    parent = None
    if request.POST.get('parent_comment'):
        parent = get_object_or_404(Comment, pk=request.POST['parent_comment'], post=post, is_removed=False)
    try:
        comment = services.add_comment(request.user, post, form.cleaned_data['body'], parent)
    except PostingBlocked as exc:
        messages.error(request, str(exc))
        return redirect(post.get_absolute_url())
    return redirect(comment.get_absolute_url())


@login_required
def edit_comment(request, pk):
    comment = get_object_or_404(Comment.objects.select_related('post'), pk=pk, is_removed=False)
    if comment.user != request.user:
        return HttpResponseForbidden(_('You can only edit your own comments.'))
    form = CommentForm(request.POST or None, instance=comment)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(comment.get_absolute_url())
    return render(request, 'comment_form.html', {'form': form, 'comment': comment})


@login_required
def delete_comment(request, pk):
    comment = get_object_or_404(Comment.objects.select_related('post'), pk=pk, is_removed=False)
    if comment.user != request.user:
        return HttpResponseForbidden(_('You can only delete your own comments.'))
    if request.method == 'POST':
        # Keep the row so replies stay attached; the thread shows a "deleted" placeholder.
        comment.is_removed = True
        comment.save(update_fields=['is_removed'])
        return redirect(comment.post.get_absolute_url())
    return render(request, 'confirm_delete.html', {'object': comment, 'label': _('comment')})


def vote_response(request, template, context, fallback):
    if request.htmx:
        return render(request, template, context)
    return redirect(safe_next_url(request, fallback))


@login_required
@require_POST
def toggle_post_vote(request, pk):
    post = get_object_or_404(Post, pk=pk, is_removed=False)
    if not services.can_view_post(request.user, post):
        raise Http404
    if post.user == request.user:
        messages.info(request, _('You cannot upvote your own post.'))
        return redirect(safe_next_url(request, post.get_absolute_url()))
    voted = services.toggle_post_vote(request.user, post)
    # Cards in lists and the vote bar on the post page swap different fragments.
    on_card = request.htmx and (request.htmx.target or '').startswith('card-vote-')
    template = 'partials/card_vote.html' if on_card else 'partials/post_vote.html'
    post.user_voted = voted
    return vote_response(request, template, {'post': post, 'user_voted': voted}, post.get_absolute_url())


@login_required
@require_POST
def toggle_comment_vote(request, pk):
    comment = get_object_or_404(Comment.objects.select_related('post', 'user'), pk=pk, is_removed=False)
    if not services.can_view_post(request.user, comment.post):
        raise Http404
    if comment.user == request.user:
        messages.info(request, _('You cannot upvote your own comment.'))
        return redirect(comment.get_absolute_url())
    comment.user_voted = services.toggle_comment_vote(request.user, comment)
    return vote_response(request, 'partials/comment_vote.html', {'comment': comment}, comment.get_absolute_url())


# --- Reports ---------------------------------------------------------------------------------

@login_required
def report_content(request, post_pk=None, comment_pk=None):
    comment = get_object_or_404(Comment.objects.select_related('post'), pk=comment_pk, is_removed=False) if comment_pk else None
    post = comment.post if comment else get_object_or_404(Post, pk=post_pk, is_removed=False)
    if not services.can_view_post(request.user, post):
        raise Http404
    target = comment or post
    form = ReportForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.file_report(request.user, form.cleaned_data['category'], form.cleaned_data['reason'], post=post, comment=comment)
            messages.success(request, _('Thanks. The moderation team will review this report.'))
        except services.ReportError as exc:
            messages.info(request, str(exc))
        return redirect(target.get_absolute_url())
    return render(request, 'report_form.html', {'form': form, 'target': target, 'post': post, 'is_comment': bool(comment)})


# --- Accounts ------------------------------------------------------------------------------------

class ThrottledLoginView(LoginView):
    """Login by username or email, locking out repeated failures (credential-stuffing protection)."""

    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if services.login_locked(request, request.POST.get('username', '')):
            messages.error(request, _('Too many failed attempts. Please wait a few minutes and try again.'))
            return self.render_to_response(self.get_context_data(form=self.get_form()), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        services.record_login_failure(self.request, self.request.POST.get('username', ''))
        return super().form_invalid(form)

    def form_valid(self, form):
        services.clear_login_failures(self.request, self.request.POST.get('username', ''))
        return super().form_valid(form)


class ThrottledPasswordResetView(PasswordResetView):
    def post(self, request, *args, **kwargs):
        if services.register_hit('pwreset', services.client_ip(request), window=3600) > 5:
            messages.error(request, _('Too many reset requests. Please try again later.'))
            return self.render_to_response(self.get_context_data(form=self.get_form()), status=429)
        return super().post(request, *args, **kwargs)


def signup(request):
    if request.user.is_authenticated:
        return redirect('home')
    form = SignUpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if services.signup_limited(request):
            messages.error(request, _('Too many sign-ups from this network. Please try again later.'))
            return render(request, 'signup.html', {'form': form}, status=429)
        if not services.turnstile_passes(request):
            messages.error(request, _('Please complete the verification challenge and try again.'))
            return render(request, 'signup.html', {'form': form}, status=400)
        user = form.save()
        login(request, user, backend='community.backends.EmailOrUsernameBackend')
        return redirect('home')
    return render(request, 'signup.html', {'form': form})


@login_required
def account_settings(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Your settings were saved.'))
        return redirect('settings')
    return render(request, 'settings.html', {'form': form})


def profile(request, username):
    profile_user = get_object_or_404(User, username=username)
    hidden_from_viewer = profile_user.is_shadow_banned and request.user != profile_user and not (request.user.is_authenticated and request.user.is_staff)
    tab = request.GET.get('tab', 'posts')
    if tab == 'comments':
        comments = profile_user.comments.filter(is_removed=False, post__is_removed=False).select_related('post', 'user')
        if hidden_from_viewer:
            comments = comments.none()
        items = paginate(request, comments.order_by('-created_at'))
    else:
        tab = 'posts'
        user_posts = services.visible_posts(request.user, profile_user.posts.select_related('category', 'asset', 'user').annotate(
            comment_count=Count('comments', filter=Q(comments__is_removed=False), distinct=True)))
        items = paginate(request, user_posts)
    return render(request, 'profile.html', {
        'profile_user': profile_user, 'tab': tab, 'items': items, 'posts': items,
        'is_following': request.user.is_authenticated and Follow.objects.filter(follower=request.user, following=profile_user).exists(),
        'follower_count': profile_user.followers.count(), 'following_count': profile_user.following.count(),
        'post_count': profile_user.posts.filter(is_removed=False).count(),
        'startup_unlock_karma': settings.REPUTATION_UNLOCKS['startup_profile'],
        'startup_unlocked': services.has_unlock(profile_user, 'startup_profile'),
        'startups': profile_user.startups.filter(is_approved=True),
    })


@login_required
@require_POST
def toggle_follow(request, username):
    target = get_object_or_404(User, username=username)
    if target == request.user:
        return redirect('profile', username=target.username)
    follow, created = Follow.objects.get_or_create(follower=request.user, following=target)
    if created:
        services.create_notification(target, request.user, 'follow', _('%(user)s followed you.') % {'user': request.user.username}, target)
    else:
        follow.delete()
    return redirect(safe_next_url(request, target.get_absolute_url()))


# --- Watchlists ----------------------------------------------------------------------------------------

@login_required
def watchlists(request):
    form = WatchlistForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        watchlist = form.save(commit=False)
        watchlist.user = request.user
        try:
            with transaction.atomic():
                watchlist.save()
            return redirect('watchlist_detail', pk=watchlist.pk)
        except IntegrityError:
            form.add_error('name', _('You already have a watchlist with this name.'))
    return render(request, 'watchlists.html', {'watchlists': request.user.watchlists.prefetch_related('items__asset'), 'form': form})


@login_required
def watchlist_detail(request, pk):
    watchlist = get_object_or_404(Watchlist.objects.prefetch_related('items__asset'), pk=pk, user=request.user)
    return render(request, 'watchlist_detail.html', {'watchlist': watchlist, 'rename_form': WatchlistForm(instance=watchlist), 'assets': asset_choices()})


@login_required
@require_POST
def rename_watchlist(request, pk):
    watchlist = get_object_or_404(Watchlist, pk=pk, user=request.user)
    form = WatchlistForm(request.POST, instance=watchlist)
    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except IntegrityError:
            messages.error(request, _('You already have a watchlist with this name.'))
    return redirect('watchlist_detail', pk=pk)


@login_required
@require_POST
def delete_watchlist(request, pk):
    get_object_or_404(Watchlist, pk=pk, user=request.user).delete()
    return redirect('watchlists')


@login_required
@require_POST
def add_watchlist_asset(request, pk):
    watchlist = get_object_or_404(Watchlist, pk=pk, user=request.user)
    asset = get_object_or_404(Tag, pk=request.POST.get('asset') or 0)
    WatchlistItem.objects.get_or_create(watchlist=watchlist, asset=asset)
    return redirect('watchlist_detail', pk=pk)


@login_required
@require_POST
def remove_watchlist_asset(request, pk, item_pk):
    get_object_or_404(WatchlistItem, pk=item_pk, watchlist__pk=pk, watchlist__user=request.user).delete()
    return redirect('watchlist_detail', pk=pk)


# --- Companies ----------------------------------------------------------------------------------------------

def find_tag(key):
    return get_object_or_404(Tag, Q(slug__iexact=key) | Q(ticker__iexact=key))


def companies(request):
    query = request.GET.get('q', '').strip()
    assets = services.search_tags(query) if query else Tag.objects.all()
    assets = assets.filter(is_company=True).annotate(
        post_count=Count('asset_posts', filter=Q(asset_posts__is_removed=False), distinct=True))
    return render(request, 'companies.html', {'assets': paginate(request, assets.order_by('ticker', 'name')), 'query': query})


def company_detail(request, slug):
    asset = find_tag(slug)
    if slug != asset.slug:
        return redirect(asset.get_absolute_url(), permanent=True)
    all_posts = services.posts_for_tag(request.user, asset)
    section = request.GET.get('section', 'recent')
    base = all_posts
    if section == 'theses':
        base = base.filter(type=Post.TYPE_THESIS)
    elif section == 'discussions':
        base = base.filter(type=Post.TYPE_DISCUSSION)
    elif section == 'ama':
        base = base.filter(type=Post.TYPE_AMA)
    else:
        section = 'recent'
    stats = all_posts.aggregate(
        total=Count('id', distinct=True), discussions=Count('id', filter=Q(type='discussion'), distinct=True),
        theses=Count('id', filter=Q(type='thesis'), distinct=True), verified=Count('id', filter=Q(user__is_verified=True), distinct=True))
    in_watchlist = request.user.is_authenticated and WatchlistItem.objects.filter(watchlist__user=request.user, asset=asset).exists()
    return render(request, 'company_detail.html', {
        'asset': asset, 'posts': paginate(request, base), 'stats': stats, 'section': section, 'in_watchlist': in_watchlist,
        'canonical_url': request.build_absolute_uri(asset.get_absolute_url()),
    })


def company_legacy_redirect(request, ticker):
    return redirect(find_tag(ticker).get_absolute_url(), permanent=True)


@login_required
@require_POST
def add_company_to_watchlist(request, slug):
    asset = find_tag(slug)
    watchlist = request.user.watchlists.order_by('created_at').first()
    if watchlist:
        WatchlistItem.objects.get_or_create(watchlist=watchlist, asset=asset)
        messages.success(request, _('%(asset)s added to %(list)s.') % {'asset': asset.name, 'list': watchlist.name})
        return redirect('watchlist_detail', pk=watchlist.pk)
    messages.info(request, _('Create a watchlist first.'))
    return redirect('watchlists')


# --- Verification --------------------------------------------------------------------------------------------------

@login_required
def verification_apply(request):
    if request.user.is_verified:
        messages.info(request, _('You are already verified.'))
        return redirect('verification_status')
    if VerificationRequest.objects.filter(user=request.user, status='pending').exists():
        messages.info(request, _('You already have an application awaiting review.'))
        return redirect('verification_status')
    form = VerificationRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        application = form.save(commit=False)
        application.user = request.user
        application.credentials_text = application.supporting_information
        try:
            with transaction.atomic():
                application.save()
        except IntegrityError:
            messages.info(request, _('You already have an application awaiting review.'))
        return redirect('verification_status')
    return render(request, 'verification_apply.html', {'form': form})


@login_required
def verification_status(request):
    return render(request, 'verification_status.html', {'applications': request.user.verification_requests.all()})


@staff_required
def verification_dashboard(request):
    status = request.GET.get('status', 'pending')
    applications = VerificationRequest.objects.select_related('user', 'reviewed_by')
    if status in dict(VerificationRequest.STATUS_CHOICES):
        applications = applications.filter(status=status)
    query = request.GET.get('q', '').strip()
    if query:
        applications = applications.filter(Q(user__username__icontains=query) | Q(full_name__icontains=query))
    return render(request, 'verification_dashboard.html', {'applications': applications, 'status': status, 'query': query})


@staff_required
def review_verification(request, pk):
    application = get_object_or_404(VerificationRequest.objects.select_related('user'), pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        form = VerificationReviewForm(request.POST)
        if application.status != VerificationRequest.STATUS_PENDING:
            messages.error(request, _('This application has already been reviewed.'))
            return redirect('verification_dashboard')
        with transaction.atomic():
            if action == 'approve':
                application.status, application.rejection_reason = 'approved', ''
                application.user.is_verified, application.user.verified_type = True, application.requested_type
                kind = 'verification_approved'
                message = _('Your verification application was approved. You are now a %(label)s.') % {'label': application.requested_type}
            elif action == 'reject' and form.is_valid():
                # Rejecting a new application never removes a badge the member already holds.
                application.status, application.rejection_reason = 'rejected', form.cleaned_data['rejection_reason']
                kind, message = 'verification_rejected', _('Your verification application was not approved.')
            else:
                messages.error(request, _('Choose a valid review action.'))
                return redirect('verification_dashboard')
            application.user.save(update_fields=['is_verified', 'verified_type'])
            application.reviewed_by, application.reviewed_at = request.user, timezone.now()
            application.save()
            services.create_notification(application.user, request.user, kind, message, application)
        return redirect('verification_dashboard')
    return render(request, 'verification_review.html', {'application': application, 'form': VerificationReviewForm()})


# --- Notifications ------------------------------------------------------------------------------------------------------

@login_required
def notifications(request):
    return render(request, 'notifications.html', {'notifications': paginate(request, request.user.notifications.select_related('actor'))})


@login_required
@require_POST
def mark_notification_read(request, pk):
    Notification.objects.filter(pk=pk, recipient=request.user).update(is_read=True)
    return redirect(safe_next_url(request, reverse('notifications')))


@login_required
@require_POST
def mark_all_notifications_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect('notifications')


# --- Search ------------------------------------------------------------------------------------------------------------------

def search(request):
    query = request.GET.get('q', '').strip()
    companies_found = users = Tag.objects.none()
    categories_found = Category.objects.none()
    results = Post.objects.none()
    if query:
        companies_found = services.search_tags(query)
        categories_found = services.search_categories(query)
        users = User.objects.filter(username__icontains=query, is_shadow_banned=False).order_by('username')
        results = services.search_posts(post_queryset(request.user), query)
    return render(request, 'search.html', {
        'query': query, 'companies': companies_found[:10], 'categories': categories_found[:10], 'users': users[:10],
        'posts': paginate(request, results) if query else [], 'filter_query': query_without_page(request),
    })


# --- Startups (V2) ------------------------------------------------------------------------------------------------------------

def startups(request):
    profiles = StartupProfile.objects.filter(is_approved=True).select_related('owner')
    query = request.GET.get('q', '').strip()
    if query:
        profiles = profiles.filter(Q(name__icontains=query) | Q(tagline__icontains=query) | Q(description__icontains=query))
    if request.GET.get('stage') in dict(StartupProfile.STAGE_CHOICES):
        profiles = profiles.filter(stage=request.GET['stage'])
    if request.GET.get('sector'):
        profiles = profiles.filter(sector__iexact=request.GET['sector'])
    sectors = (StartupProfile.objects.filter(is_approved=True).exclude(sector='').values_list('sector', flat=True).distinct().order_by('sector'))
    return render(request, 'startups.html', {
        'profiles': paginate(request, profiles), 'query': query, 'sectors': sectors, 'stages': StartupProfile.STAGE_CHOICES,
        'filter_query': query_without_page(request),
    })


def startup_detail(request, slug):
    profile_obj = get_object_or_404(StartupProfile.objects.select_related('owner'), slug=slug)
    is_owner = request.user.is_authenticated and request.user == profile_obj.owner
    if not profile_obj.is_approved and not (is_owner or (request.user.is_authenticated and request.user.is_staff)):
        raise Http404
    return render(request, 'startup_detail.html', {'startup': profile_obj, 'is_owner': is_owner, 'canonical_url': request.build_absolute_uri(profile_obj.get_absolute_url())})


@login_required
def startup_create(request):
    if not services.has_unlock(request.user, 'startup_profile'):
        messages.info(request, _('Startup profiles unlock at %(karma)s reputation, or with a verified badge. Keep contributing to the community!') % {
            'karma': settings.REPUTATION_UNLOCKS['startup_profile']})
        return redirect('startups')
    if request.user.startups.count() >= 3:
        messages.info(request, _('You can list up to 3 startups.'))
        return redirect('startups')
    form = StartupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        profile_obj = form.save(commit=False)
        profile_obj.owner = request.user
        profile_obj.is_approved = request.user.is_staff
        profile_obj.save()
        messages.success(request, _('Your startup profile was submitted and will appear once a moderator approves it.'))
        return redirect(profile_obj.get_absolute_url())
    return render(request, 'startup_form.html', {'form': form, 'editing': False})


@login_required
def startup_edit(request, slug):
    profile_obj = get_object_or_404(StartupProfile, slug=slug, owner=request.user)
    form = StartupForm(request.POST or None, instance=profile_obj)
    if request.method == 'POST' and form.is_valid():
        profile_obj = form.save(commit=False)
        if not request.user.is_staff:
            profile_obj.is_approved = False  # edits are re-reviewed so approved pages cannot be swapped for spam
        profile_obj.save()
        messages.success(request, _('Saved. Changes are visible publicly once a moderator approves them.'))
        return redirect(profile_obj.get_absolute_url())
    return render(request, 'startup_form.html', {'form': form, 'editing': True, 'startup': profile_obj})


# --- News (staff-written editorial content) -----------------------------------------------------------------------------------------

def news_list(request):
    articles = paginate(request, NewsPost.objects.select_related('author'))
    return render(request, 'news_list.html', {'articles': articles})


def news_detail(request, slug):
    article = get_object_or_404(NewsPost, slug=slug)
    return render(request, 'news_detail.html', {'article': article})


@staff_required
def news_create(request):
    form = NewsForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        article = form.save(commit=False)
        article.author = request.user
        article.save()
        messages.success(request, _('News article published.'))
        return redirect(article.get_absolute_url())
    return render(request, 'news_form.html', {'form': form, 'editing': False})


@staff_required
def news_edit(request, slug):
    article = get_object_or_404(NewsPost, slug=slug)
    form = NewsForm(request.POST or None, request.FILES or None, instance=article)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('News article updated.'))
        return redirect(article.get_absolute_url())
    return render(request, 'news_form.html', {'form': form, 'editing': True, 'article': article})


@staff_required
def news_delete(request, slug):
    article = get_object_or_404(NewsPost, slug=slug)
    if request.method == 'POST':
        article.delete()
        messages.success(request, _('News article deleted.'))
        return redirect('news_list')
    return render(request, 'confirm_delete.html', {'object': article, 'label': _('news article')})


# --- Markdown editor ---------------------------------------------------------------------------------------------------------------

@login_required
@require_POST
def markdown_preview(request):
    """Render the composer's live Preview tab using the exact same pipeline as a published post or
    comment, so what a member sees here is guaranteed to match what actually gets published."""
    if services.register_hit('md-preview', request.user.pk, window=60) > 30:
        return HttpResponse(status=429)
    text = request.POST.get('body', '')
    return render(request, 'partials/markdown_preview.html', {'rendered': markdown_safe(text) if text.strip() else None})


# --- Static pages, robots ------------------------------------------------------------------------------------------------------------

def guidelines(request):
    return render(request, 'pages/guidelines.html')


def disclaimer(request):
    return render(request, 'pages/disclaimer.html')


def privacy(request):
    return render(request, 'pages/privacy.html')


def terms(request):
    return render(request, 'pages/terms.html')


def about(request):
    return render(request, 'pages/about.html')


def contact(request):
    initial = {'name': request.user.username, 'email': request.user.email} if request.user.is_authenticated else {}
    form = ContactForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        if services.contact_limited(request):
            messages.error(request, _('Too many messages from this network. Please try again later.'))
            return render(request, 'pages/contact.html', {'form': form}, status=429)
        if not services.turnstile_passes(request):
            messages.error(request, _('Please complete the verification challenge and try again.'))
            return render(request, 'pages/contact.html', {'form': form}, status=400)
        contact_message = form.save(commit=False)
        if request.user.is_authenticated:
            contact_message.user = request.user
        contact_message.save()
        messages.success(request, _("Thanks — we've received your message and will get back to you soon."))
        return redirect('contact')
    return render(request, 'pages/contact.html', {'form': form})


def robots_txt(request):
    lines = ['User-agent: *', 'Disallow: /admin/', 'Disallow: /moderation/', 'Disallow: /verification/review/', 'Disallow: /accounts/',
             'Disallow: /auth/', 'Disallow: /api/', 'Disallow: /notifications/', 'Disallow: /settings/', 'Disallow: /watchlists/',
             f'Sitemap: {request.build_absolute_uri(reverse("sitemap"))}']
    return HttpResponse('\n'.join(lines) + '\n', content_type='text/plain')
