import os

import markdown
import nh3
from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import Truncator

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
