from django.conf import settings

from .models import Category


def site(request):
    return {
        'SITE_NAME': settings.SITE_NAME, 'google_login_enabled': settings.GOOGLE_LOGIN_ENABLED,
        'turnstile_site_key': settings.TURNSTILE_SITE_KEY,
    }


def notification_counts(request):
    if request.user.is_authenticated:
        return {
            'unread_notification_count': request.user.notifications.filter(is_read=False).count(),
            'recent_notifications': request.user.notifications.select_related('actor')[:5],
        }
    return {'unread_notification_count': 0, 'recent_notifications': []}


def sidebar_nav(request):
    """Categories for the persistent site-wide sidebar (every page, not just the home feed)."""
    followed = set()
    if request.user.is_authenticated:
        followed = set(request.user.category_follows.values_list('category_id', flat=True))
    return {'sidebar_categories': Category.objects.all(), 'sidebar_followed_categories': followed}
