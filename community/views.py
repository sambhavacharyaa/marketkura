from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CommentForm, PostForm, ReportForm, SignUpForm
from .models import Comment, Category, Post, PostVote, Report, User


def home(request):
    categories = Category.objects.all()
    query = request.GET.get('q', '').strip()
    posts = Post.objects.select_related('user', 'category').annotate(comment_count=Count('comments'))
    if query:
        posts = posts.filter(Q(title__icontains=query) | Q(body__icontains=query) | Q(asset_tag__icontains=query))
    return render(request, 'home.html', {'categories': categories, 'posts': posts, 'query': query})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    posts = Post.objects.filter(category=category).select_related('user', 'category')
    return render(request, 'category_detail.html', {'category': category, 'posts': posts})


def post_detail(request, pk):
    post = get_object_or_404(Post.objects.select_related('user', 'category'), pk=pk)
    comments = post.comments.filter(parent_comment__isnull=True).select_related('user').prefetch_related('replies__user')
    return render(request, 'post_detail.html', {
        'post': post,
        'comments': comments,
        'comment_form': CommentForm(),
        'report_form': ReportForm(),
        'user_voted': request.user.is_authenticated and post.votes.filter(user=request.user).exists(),
    })


@login_required
def create_post(request):
    form = PostForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        post = form.save(commit=False)
        post.user = request.user
        post.save()
        messages.success(request, 'Your post is live.')
        return redirect('post_detail', pk=post.pk)
    return render(request, 'post_form.html', {'form': form})


@login_required
def add_comment(request, pk):
    post = get_object_or_404(Post, pk=pk)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.post = post
        comment.user = request.user
        comment.save()
    return redirect('post_detail', pk=post.pk)


@login_required
def toggle_post_vote(request, pk):
    post = get_object_or_404(Post, pk=pk)
    vote, created = PostVote.objects.get_or_create(post=post, user=request.user)
    if not created:
        vote.delete()
    post.upvotes = post.votes.count()
    post.save(update_fields=['upvotes'])
    return redirect(request.POST.get('next') or request.META.get('HTTP_REFERER') or 'home')


def signup(request):
    if request.user.is_authenticated:
        return redirect('home')
    form = SignUpForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('home')
    return render(request, 'signup.html', {'form': form})


def profile(request, username):
    user = get_object_or_404(User, username=username)
    posts = user.posts.select_related('category')
    return render(request, 'profile.html', {'profile_user': user, 'posts': posts})


@login_required
def report_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    form = ReportForm(request.POST)
    if form.is_valid():
        Report.objects.create(post=post, reporter=request.user, reason=form.cleaned_data['reason'])
        messages.success(request, 'Thanks. The moderation team will review this report.')
    return redirect('post_detail', pk=post.pk)
