"""Thin client for Finnhub's free tier: real-time-ish quotes and per-company news for the
Companies section's global (non-NEPSE) tickers.

Every function degrades to None/[] on any failure — no API key configured, a timeout, a rate
limit, or a symbol Finnhub doesn't recognise (which it reports as all-zero fields, not an error).
refresh_market_data runs unattended on a schedule, so one bad symbol or a blip in Finnhub's own
service should never stop the rest of the batch or raise out of a cron job.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

BASE_URL = 'https://finnhub.io/api/v1'
TIMEOUT = 10


def _get(path, params):
    if not settings.FINNHUB_API_KEY:
        return None
    try:
        response = requests.get(f'{BASE_URL}/{path}', params={**params, 'token': settings.FINNHUB_API_KEY}, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logger.warning('Finnhub request to %s failed: %s', path, exc)
        return None


def get_quote(symbol):
    """Current price/change for symbol, or None if unavailable (including an unknown symbol)."""
    data = _get('quote', {'symbol': symbol})
    if not data or not data.get('c'):
        return None
    return {'price': data['c'], 'change': data.get('d'), 'change_percent': data.get('dp')}


def get_company_news(symbol, days=7):
    """Up to Finnhub's own cap of recent headlines for symbol from the last `days` days.

    Each item: headline, url, source, published_at (an aware UTC datetime).
    """
    today = timezone.now().date()
    data = _get('company-news', {'symbol': symbol, 'from': (today - timedelta(days=days)).isoformat(), 'to': today.isoformat()})
    if not data:
        return []
    items = []
    for item in data:
        if not item.get('headline') or not item.get('url') or not item.get('datetime'):
            continue
        items.append({
            'headline': item['headline'][:500],
            'url': item['url'][:1000],
            'source': (item.get('source') or '')[:120],
            'published_at': datetime.fromtimestamp(item['datetime'], tz=dt_timezone.utc),
        })
    return items
