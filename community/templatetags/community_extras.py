import os
import zoneinfo

import markdown
import nh3
from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from django.utils.translation import get_language
from django.utils.translation import gettext as _

register = template.Library()

ALLOWED_TAGS = {
    'p', 'br', 'strong', 'em', 'del', 'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'hr',
    'a', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
}


@register.filter
def markdown_safe(text):
    """Render member-written Markdown to HTML that is safe to output.

    Markdown may contain raw HTML, so the rendered result is always run through nh3 with an
    allow-list: no images, scripts, styles or event handlers, and only http(s)/mailto links.
    """
    html = markdown.markdown(text or '', extensions=['nl2br', 'fenced_code', 'tables'])
    clean = nh3.clean(
        html, tags=ALLOWED_TAGS, attributes={'a': {'href', 'title'}},
        url_schemes={'http', 'https', 'mailto'}, link_rel='nofollow ugc noopener noreferrer',
    )
    return mark_safe(clean)


@register.filter
def excerpt(text, words=30):
    """Plain-text preview of a Markdown body for list pages and meta descriptions."""
    plain = strip_tags(markdown.markdown(text or ''))
    return Truncator(plain).words(int(words), truncate='…')


@register.simple_tag(takes_context=True)
def query_string(context, **overrides):
    """Current GET parameters with the given overrides (used for pagination and filters)."""
    query = context['request'].GET.copy()
    for key, value in overrides.items():
        if value in (None, ''):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


@register.filter
def read_minutes(text):
    """Estimated reading time in whole minutes (at least 1), assuming ~200 words per minute."""
    return max(1, round(len((text or '').split()) / 200))


# Icon shown next to each category in the sidebar/rail. Keyed by slug rather than stored on the
# model — these are the fixed blueprint categories (see the 0006_seed_categories migration); any
# category outside this list (added later via the admin) just falls back to a plain tag icon.
CATEGORY_ICONS = {
    'global-markets': 'globe',
    'market-news': 'news',
    'nepse': 'chart',
    'personal-finance': 'wallet',
    'startups-founders': 'rocket',
    'trading-strategy': 'target',
}


@register.filter
def category_icon(category):
    return CATEGORY_ICONS.get(category.slug, 'hash')


# Largest-to-smallest, same two-unit breakdown as Django's own naturaltime (e.g. "1 month, 3
# weeks ago") - matched here rather than reused because django.contrib.humanize's bundled Nepali
# translations are incomplete: unit words fall back to English and the wrapping string drops its
# spacing, producing "1 month,3 weeksपहिले". Nepali unit words don't inflect for plural, so there's
# no separate singular/plural form to carry here the way English needs one.
_TIME_CHUNKS = (
    (60 * 60 * 24 * 365, 'year', 'वर्ष'),
    (60 * 60 * 24 * 30, 'month', 'महिना'),
    (60 * 60 * 24 * 7, 'week', 'हप्ता'),
    (60 * 60 * 24, 'day', 'दिन'),
    (60 * 60, 'hour', 'घण्टा'),
    (60, 'minute', 'मिनेट'),
)


def _english_unit(count, unit):
    return f'{count} {unit}' if count == 1 else f'{count} {unit}s'


@register.filter
def local_naturaltime(value):
    """Relative time ("1 month, 3 weeks ago" / "१ महिना ३ हप्ता अघि"), correctly spaced and worded
    in both languages this site supports. See _TIME_CHUNKS above for why this doesn't just use
    django.contrib.humanize's naturaltime."""
    if not value:
        return ''
    delta = timezone.now() - value
    seconds = delta.total_seconds()
    future = seconds < 0
    seconds = abs(seconds)
    is_nepali = get_language() == 'ne'

    if seconds < 60:
        if future:
            return 'केही बेरमा' if is_nepali else _('in a moment')
        return 'भर्खरै' if is_nepali else _('just now')

    parts = []
    remaining = int(seconds)
    for chunk_seconds, unit_en, unit_ne in _TIME_CHUNKS:
        if remaining < chunk_seconds:
            continue
        count = remaining // chunk_seconds
        parts.append((count, unit_en, unit_ne))
        remaining -= count * chunk_seconds
        if len(parts) == 2:
            break
    if not parts:
        parts = [(max(1, int(seconds // 60)), 'minute', 'मिनेट')]

    if is_nepali:
        delta_str = ' '.join(f'{count} {unit_ne}' for count, _unit_en, unit_ne in parts)
        return f'{delta_str} पछि' if future else f'{delta_str} अघि'

    delta_str = ', '.join(_english_unit(count, unit_en) for count, unit_en, _unit_ne in parts)
    return (_('%(delta)s from now') if future else _('%(delta)s ago')) % {'delta': delta_str}


# The server stores and would otherwise display everything in UTC (settings.TIME_ZONE), which is
# meaningless to almost every reader of a Nepal-focused platform. Converting to Asia/Kathmandu
# (UTC+5:45, no DST) and labelling it "NPT" removes that silent mismatch without needing a
# visitor-by-visitor timezone guess.
_KATHMANDU_TZ = zoneinfo.ZoneInfo('Asia/Kathmandu')


@register.filter
def nepal_time(value):
    """Short absolute timestamp in Nepal time, e.g. "Sep 04, 2026 14:42 NPT"."""
    if not value:
        return ''
    return f"{timezone.localtime(value, _KATHMANDU_TZ).strftime('%b %d, %Y %H:%M')} NPT"


@register.filter
def nepal_time_full(value):
    """Fuller timestamp (weekday + seconds) for a title tooltip on the short version above."""
    if not value:
        return ''
    return f"{timezone.localtime(value, _KATHMANDU_TZ).strftime('%A, %B %d, %Y, %H:%M:%S')} NPT"


@register.simple_tag
def static_v(path):
    """Like {% static %}, but appends `?v=<mtime>` so CSS/JS edits are picked up on the next
    request instead of sitting behind the browser's cache until a hard refresh — static/css/main.css
    and the app's own JS have no content hash in their URL (no ManifestStaticFilesStorage), so
    without this a change here is invisible to anyone with a previously-cached copy."""
    url = static(path)
    found = finders.find(path)
    if found:
        try:
            url = f'{url}?v={int(os.path.getmtime(found))}'
        except OSError:
            pass
    return url
