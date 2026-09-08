from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .forms import CommentForm, PostForm, ReportForm, SignUpForm, VerificationRequestForm, VerificationReviewForm, WatchlistForm
from .models import Category, Comment, Follow, Notification, Post, PostVote, Report, Tag, User, VerificationRequest, Watchlist, WatchlistItem


def paginate(request, queryset, per_page=12):
    if not queryset.ordered:
        queryset = queryset.order_by('-created_at')
    return Paginator(queryset, per_page).get_page(request.GET.get('page'))


def query_without_page(request):
    query = request.GET.copy()
    query.pop('page', None)
    return query.urlencode()


def post_queryset():
    return Post.objects.select_related('user', 'category', 'asset').annotate(comment_count=Count('comments'))


def asset_from_post(post):
    if not post.asset_id and (post.asset_tag or '').strip():
        ticker = post.asset_tag.strip().upper()
        post.asset = Tag.objects.filter(Q(ticker__iexact=ticker) | Q(slug__iexact=slugify(ticker))).first()
        if not post.asset:
            post.asset = Tag.objects.create(ticker=ticker, name=ticker, slug=slugify(ticker))


def create_notification(recipient, actor, kind, message, target=None):
    if recipient == actor:
        return
    Notification.objects.create(recipient=recipient, actor=actor, notification_type=kind, message=message,
        target_type=target.__class__.__name__.lower() if target else '', target_id=target.pk if target else None,
        target_url=target.get_absolute_url() if target and hasattr(target, 'get_absolute_url') else '')


def notify_mentions(text, actor, target):
    for username in {part[1:].rstrip('.,!?:;') for part in text.split() if part.startswith('@') and len(part) > 1}:
        recipient = User.objects.filter(username__iexact=username).first()
        if recipient: create_notification(recipient, actor, 'mention', f'{actor.username} mentioned you.', target)


def apply_post_filters(request, posts):
    query = request.GET.get('q', '').strip()
    if query: posts = posts.filter(Q(title__icontains=query) | Q(body__icontains=query) | Q(asset_tag__icontains=query) | Q(asset__ticker__icontains=query) | Q(asset__company_name__icontains=query))
    if request.GET.get('type') in dict(Post.POST_TYPES): posts = posts.filter(type=request.GET['type'])
    if request.GET.get('asset'): posts = posts.filter(Q(asset__ticker__iexact=request.GET['asset']) | Q(asset__slug__iexact=request.GET['asset']))
    if request.GET.get('verified') == '1': posts = posts.filter(user__is_verified=True)
    if request.GET.get('position') in ('long', 'short', 'watching'): posts = posts.filter(position_type=request.GET['position'])
    if request.GET.get('horizon') in ('short', 'medium', 'long'): posts = posts.filter(time_horizon=request.GET['horizon'])
    if request.GET.get('date') == 'week': posts = posts.filter(created_at__gte=timezone.now() - timedelta(days=7))
    return posts.order_by('-comment_count', '-upvotes', '-created_at') if request.GET.get('sort') == 'discussed' else posts


def home(request):
    return render(request, 'home.html', {'categories': Category.objects.all(), 'posts': paginate(request, apply_post_filters(request, post_queryset())), 'query': request.GET.get('q', '').strip(), 'assets': Tag.objects.order_by('ticker', 'name'), 'filter_query': query_without_page(request)})


def posts(request):
    return render(request, 'posts.html', {'posts': paginate(request, apply_post_filters(request, post_queryset())), 'assets': Tag.objects.order_by('ticker', 'name'), 'filter_query': query_without_page(request)})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    return render(request, 'category_detail.html', {'category': category, 'posts': paginate(request, post_queryset().filter(category=category))})


def post_detail(request, pk):
    post = get_object_or_404(post_queryset(), pk=pk)
    comments = post.comments.filter(parent_comment__isnull=True).select_related('user').prefetch_related('replies__user')
    return render(request, 'post_detail.html', {'post': post, 'comments': comments, 'comment_form': CommentForm(), 'report_form': ReportForm(), 'user_voted': request.user.is_authenticated and post.votes.filter(user=request.user).exists()})


@login_required
def create_post(request):
    form = PostForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        post = form.save(commit=False); post.user = request.user; asset_from_post(post); post.save()
        notify_mentions(post.body, request.user, post)
        messages.success(request, 'Your post is live. Posts are user-generated and theses are self-reported.')
        return redirect('post_detail', pk=post.pk)
    return render(request, 'post_form.html', {'form': form, 'editing': False})


@login_required
def edit_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if post.user != request.user: return HttpResponseForbidden('You can only edit your own posts.')
    form = PostForm(request.POST or None, instance=post)
    if request.method == 'POST' and form.is_valid():
        post = form.save(commit=False); asset_from_post(post); post.save(); return redirect('post_detail', pk=post.pk)
    return render(request, 'post_form.html', {'form': form, 'editing': True, 'post': post})


@login_required
def delete_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    if post.user != request.user: return HttpResponseForbidden('You can only delete your own posts.')
    if request.method == 'POST': post.delete(); return redirect('home')
    return render(request, 'confirm_delete.html', {'object': post, 'label': 'post'})


@login_required
@require_POST
def add_comment(request, pk):
    post = get_object_or_404(Post, pk=pk); form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False); comment.post = post; comment.user = request.user
        if request.POST.get('parent_comment'): comment.parent_comment = get_object_or_404(Comment, pk=request.POST['parent_comment'], post=post)
        comment.save(); recipient = comment.parent_comment.user if comment.parent_comment else post.user
        create_notification(recipient, request.user, 'reply' if comment.parent_comment else 'comment', f'{request.user.username} commented on your post.', post); notify_mentions(comment.body, request.user, post)
    return redirect('post_detail', pk=post.pk)


@login_required
@require_POST
def toggle_post_vote(request, pk):
    post = get_object_or_404(Post, pk=pk); vote, created = PostVote.objects.get_or_create(post=post, user=request.user)
    if not created: vote.delete()
    else: create_notification(post.user, request.user, 'reaction', f'{request.user.username} reacted to your post.', post)
    post.upvotes = post.votes.count(); post.save(update_fields=['upvotes'])
    return redirect(request.POST.get('next') or request.META.get('HTTP_REFERER') or 'home')


def signup(request):
    if request.user.is_authenticated: return redirect('home')
    form = SignUpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid(): user = form.save(); login(request, user); return redirect('home')
    return render(request, 'signup.html', {'form': form})


def profile(request, username):
    user = get_object_or_404(User, username=username)
    return render(request, 'profile.html', {'profile_user': user, 'posts': paginate(request, user.posts.select_related('category', 'asset')), 'is_following': request.user.is_authenticated and Follow.objects.filter(follower=request.user, following=user).exists()})


@login_required
@require_POST
def toggle_follow(request, username):
    target = get_object_or_404(User, username=username)
    if target == request.user:
        return redirect('profile', username=target.username)
    follow, created = Follow.objects.get_or_create(follower=request.user, following=target)
    if created:
        create_notification(target, request.user, 'follow', f'{request.user.username} followed you.', target)
    else:
        follow.delete()
    return redirect(request.POST.get('next') or 'profile', username=target.username)


@login_required
def report_post(request, pk):
    post = get_object_or_404(Post, pk=pk); form = ReportForm(request.POST)
    if form.is_valid(): Report.objects.create(post=post, reporter=request.user, reason=form.cleaned_data['reason']); messages.success(request, 'Thanks. The moderation team will review this report.')
    return redirect('post_detail', pk=post.pk)


@login_required
def watchlists(request):
    form = WatchlistForm(request.POST or None)
    if request.method == 'POST' and form.is_valid(): watchlist = form.save(commit=False); watchlist.user = request.user; watchlist.save(); return redirect('watchlist_detail', pk=watchlist.pk)
    return render(request, 'watchlists.html', {'watchlists': request.user.watchlists.prefetch_related('items__asset'), 'form': form})


@login_required
def watchlist_detail(request, pk):
    watchlist = get_object_or_404(Watchlist.objects.prefetch_related('items__asset'), pk=pk, user=request.user)
    return render(request, 'watchlist_detail.html', {'watchlist': watchlist, 'rename_form': WatchlistForm(instance=watchlist), 'assets': Tag.objects.order_by('ticker', 'name')})


@login_required
@require_POST
def rename_watchlist(request, pk):
    watchlist = get_object_or_404(Watchlist, pk=pk, user=request.user); form = WatchlistForm(request.POST, instance=watchlist)
    if form.is_valid(): form.save()
    return redirect('watchlist_detail', pk=pk)


@login_required
@require_POST
def delete_watchlist(request, pk):
    watchlist = get_object_or_404(Watchlist, pk=pk, user=request.user)
    if request.method == 'POST': watchlist.delete(); return redirect('watchlists')
    return render(request, 'confirm_delete.html', {'object': watchlist, 'label': 'watchlist'})


@login_required
@require_POST
def add_watchlist_asset(request, pk):
    watchlist = get_object_or_404(Watchlist, pk=pk, user=request.user); asset = get_object_or_404(Tag, pk=request.POST.get('asset'))
    WatchlistItem.objects.get_or_create(watchlist=watchlist, asset=asset); return redirect('watchlist_detail', pk=pk)


@login_required
@require_POST
def remove_watchlist_asset(request, pk, item_pk):
    get_object_or_404(WatchlistItem, pk=item_pk, watchlist__pk=pk, watchlist__user=request.user).delete(); return redirect('watchlist_detail', pk=pk)


def companies(request):
    query = request.GET.get('q', '').strip()
    assets = Tag.objects.annotate(post_count=Count('asset_posts'))
    if query:
        assets = assets.filter(Q(ticker__icontains=query) | Q(name__icontains=query) | Q(company_name__icontains=query))
    return render(request, 'companies.html', {'assets': paginate(request, assets.order_by('ticker', 'name')), 'query': query})


def company_detail(request, ticker):
    asset = get_object_or_404(Tag, Q(ticker__iexact=ticker) | Q(slug__iexact=ticker)); all_posts = post_queryset().filter(asset=asset); base = all_posts; section = request.GET.get('section', 'recent')
    if section == 'theses': base = base.filter(type='thesis')
    if section == 'discussions': base = base.filter(type='discussion')
    stats = all_posts.aggregate(total=Count('id'), discussions=Count('id', filter=Q(type='discussion')), theses=Count('id', filter=Q(type='thesis')), verified=Count('id', filter=Q(user__is_verified=True)))
    return render(request, 'company_detail.html', {'asset': asset, 'posts': paginate(request, base), 'stats': stats, 'section': section, 'canonical_url': request.build_absolute_uri(reverse('company_detail', args=[asset.ticker or asset.slug]))})


@login_required
@require_POST
def add_company_to_watchlist(request, ticker):
    asset = get_object_or_404(Tag, Q(ticker__iexact=ticker) | Q(slug__iexact=ticker)); watchlist = request.user.watchlists.order_by('created_at').first()
    if watchlist: WatchlistItem.objects.get_or_create(watchlist=watchlist, asset=asset); messages.success(request, f'{asset.name} added to {watchlist.name}.'); return redirect('watchlist_detail', pk=watchlist.pk)
    messages.info(request, 'Create a watchlist first.'); return redirect('watchlists')


@login_required
def verification_apply(request):
    if VerificationRequest.objects.filter(user=request.user, status='pending').exists(): messages.info(request, 'You already have an application awaiting review.'); return redirect('verification_status')
    form = VerificationRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid(): application = form.save(commit=False); application.user = request.user; application.credentials_text = application.supporting_information; application.save(); return redirect('verification_status')
    return render(request, 'verification_apply.html', {'form': form})


@login_required
def verification_status(request): return render(request, 'verification_status.html', {'applications': request.user.verification_requests.all()})


@user_passes_test(lambda user: user.is_staff)
def verification_dashboard(request):
    status = request.GET.get('status', 'pending'); applications = VerificationRequest.objects.select_related('user', 'reviewed_by')
    if status in dict(VerificationRequest.STATUS_CHOICES): applications = applications.filter(status=status)
    query = request.GET.get('q', '').strip()
    if query: applications = applications.filter(Q(user__username__icontains=query) | Q(full_name__icontains=query))
    return render(request, 'verification_dashboard.html', {'applications': applications, 'status': status, 'query': query})


@user_passes_test(lambda user: user.is_staff)
def review_verification(request, pk):
    application = get_object_or_404(VerificationRequest, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action'); form = VerificationReviewForm(request.POST)
        if action == 'approve': application.status, application.rejection_reason, application.user.is_verified, application.user.verified_type, kind, message = 'approved', '', True, 'Verified Contributor', 'verification_approved', 'Your verification application was approved. You are now a Verified Contributor.'
        elif action == 'reject' and form.is_valid(): application.status, application.rejection_reason, application.user.is_verified, application.user.verified_type, kind, message = 'rejected', form.cleaned_data['rejection_reason'], False, '', 'verification_rejected', 'Your verification application was not approved.'
        else: messages.error(request, 'Choose a valid review action.'); return redirect('verification_dashboard')
        application.user.save(update_fields=['is_verified', 'verified_type']); application.reviewed_by, application.reviewed_at = request.user, timezone.now(); application.save(); create_notification(application.user, request.user, kind, message, application); return redirect('verification_dashboard')
    return render(request, 'verification_review.html', {'application': application, 'form': VerificationReviewForm()})


@login_required
def notifications(request): return render(request, 'notifications.html', {'notifications': paginate(request, request.user.notifications.select_related('actor'))})


@login_required
@require_POST
def mark_notification_read(request, pk): Notification.objects.filter(pk=pk, recipient=request.user).update(is_read=True); return redirect(request.POST.get('next') or 'notifications')


@login_required
@require_POST
def mark_all_notifications_read(request): request.user.notifications.filter(is_read=False).update(is_read=True); return redirect('notifications')


def search(request):
    query = request.GET.get('q', '').strip(); companies = users = Tag.objects.none(); results = Post.objects.none()
    if query:
        companies = Tag.objects.filter(Q(ticker__icontains=query) | Q(name__icontains=query) | Q(company_name__icontains=query)).order_by('ticker', 'name')
        users = User.objects.filter(username__icontains=query).order_by('username')
        results = post_queryset().filter(Q(title__icontains=query) | Q(body__icontains=query) | Q(asset__ticker__icontains=query) | Q(asset__company_name__icontains=query))
    return render(request, 'search.html', {'query': query, 'companies': companies[:10], 'users': users[:10], 'posts': paginate(request, results) if query else []})
