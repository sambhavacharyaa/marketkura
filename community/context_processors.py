from django.conf import settings
from django.utils.translation import gettext as _

from .models import Category


def site(request):
    return {
        'SITE_NAME': settings.SITE_NAME, 'google_login_enabled': settings.GOOGLE_LOGIN_ENABLED,
        'turnstile_site_key': settings.TURNSTILE_SITE_KEY,
        # rich-editor.js's toolbar is pure JS (no server round-trip per keystroke), so its button
        # labels can't go through {% trans %} directly - passed in instead via json_script in
        # base.html, read back out in rich-editor.js. Keyed to match static/js/rich-editor.js's
        # BUTTONS list and its Write/Preview tabs.
        'md_toolbar_labels': {
            'bold': _('Bold'), 'italic': _('Italic'), 'strike': _('Strikethrough'),
            'heading': _('Heading'), 'quote': _('Quote'), 'code': _('Code'),
            'bullet': _('Bulleted list'), 'numbered': _('Numbered list'), 'link': _('Link'),
            'write': _('Write'), 'preview': _('Preview'),
        },
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
