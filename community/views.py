from django.shortcuts import get_object_or_404, render

from .models import Category, Post


def home(request):
    categories = Category.objects.all()
    posts = Post.objects.select_related('user', 'category').all()
    return render(request, 'home.html', {'categories': categories, 'posts': posts})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    posts = Post.objects.filter(category=category).select_related('user', 'category')
    return render(request, 'category_detail.html', {'category': category, 'posts': posts})


def post_detail(request, pk):
    post = get_object_or_404(Post.objects.select_related('user', 'category'), pk=pk)
    return render(request, 'post_detail.html', {'post': post})
