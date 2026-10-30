from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Category, NewsPost, Post, StartupProfile, Tag


class StaticSitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.6

    def items(self):
        return ['home', 'companies', 'startups', 'news_list', 'guidelines', 'privacy', 'terms', 'about', 'contact']

    def location(self, name):
        return reverse(name)


class CategorySitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.8

    def items(self):
        return Category.objects.all()


class CompanySitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.9

    def items(self):
        return Tag.objects.filter(asset_posts__is_removed=False, asset_posts__user__is_shadow_banned=False).distinct().order_by('slug')


class PostSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7
    limit = 2000

    def items(self):
        return Post.objects.filter(is_removed=False, user__is_shadow_banned=False).select_related('user').order_by('-created_at')

    def lastmod(self, post):
        return post.updated_at


class StartupSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        return StartupProfile.objects.filter(is_approved=True)

    def lastmod(self, startup):
        return startup.updated_at


class NewsSitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.6

    def items(self):
        return NewsPost.objects.all()

    def lastmod(self, article):
        return article.updated_at


SITEMAPS = {
    'static': StaticSitemap, 'categories': CategorySitemap, 'companies': CompanySitemap,
    'posts': PostSitemap, 'startups': StartupSitemap, 'news': NewsSitemap,
}
