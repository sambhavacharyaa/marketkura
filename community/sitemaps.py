import os
from datetime import datetime, timezone as dt_timezone

from django.contrib.sitemaps import Sitemap
from django.template import loader
from django.urls import reverse

from .models import Category, NewsPost, Post, StartupProfile, Tag

# Static pages have no database row to read an update time from, so lastmod falls back to the
# page's own template file's mtime on disk — a genuine "last changed" signal, not a fabricated one.
STATIC_TEMPLATES = {
    'home': 'home.html', 'companies': 'companies.html', 'startups': 'startups.html',
    'news_list': 'news_list.html', 'guidelines': 'pages/guidelines.html', 'disclaimer': 'pages/disclaimer.html',
    'privacy': 'pages/privacy.html', 'terms': 'pages/terms.html', 'about': 'pages/about.html',
    'contact': 'pages/contact.html',
}


class StaticSitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.6

    def items(self):
        return list(STATIC_TEMPLATES)

    def location(self, name):
        return reverse(name)

    def lastmod(self, name):
        template = loader.get_template(STATIC_TEMPLATES[name])
        try:
            return datetime.fromtimestamp(os.path.getmtime(template.origin.name), tz=dt_timezone.utc)
        except OSError:
            return None


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
