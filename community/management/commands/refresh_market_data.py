"""Refresh live price, a price-history point, and recent news for every company Tag with a
ticker, from Finnhub.

Meant to run on a schedule (e.g. every few minutes via cron — see the deploy notes), not on every
page render: it writes to the database, while the Companies section itself only ever reads the
cached Tag/CompanyNews rows this command maintains.

Only ever adds or updates fields with fresh, valid data. A ticker Finnhub doesn't recognise —
mainly NEPSE ones, since Finnhub has no NEPSE coverage; see refresh_nepse_market_data for those —
is silently skipped, leaving whatever data, if any, it already had untouched. Without
FINNHUB_API_KEY configured, every company is skipped and the command exits cleanly.

Usage:
    manage.py refresh_market_data
    manage.py refresh_market_data --dry-run
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from community import services
from community.finnhub_client import get_company_news, get_quote
from community.models import CompanyNews, Tag

# One quote call + one news call per company; a short pause between companies keeps well under
# Finnhub's free-tier 60-calls/minute limit even for a sizeable company list.
PAUSE_SECONDS = 1.1
NEWS_DAYS = 7
NEWS_KEPT_PER_COMPANY = 15


class Command(BaseCommand):
    help = "Refresh Tag price fields and CompanyNews from Finnhub for every company with a ticker."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Fetch and report, but write nothing.')

    def handle(self, *args, **options):
        if not settings.FINNHUB_API_KEY:
            self.stdout.write(self.style.WARNING('FINNHUB_API_KEY is not set — nothing to do.'))
            return
        dry_run = options['dry_run']
        prefix = '[dry-run] would ' if dry_run else ''
        updated = skipped = news_added = 0
        tickers = list(Tag.objects.filter(is_company=True).exclude(ticker='').exclude(ticker__isnull=True))
        for i, tag in enumerate(tickers):
            if i:
                time.sleep(PAUSE_SECONDS)
            quote = get_quote(tag.ticker)
            if quote is None:
                skipped += 1
                continue
            if not dry_run:
                tag.last_price = quote['price']
                tag.price_change = quote['change']
                tag.price_change_percent = quote['change_percent']
                tag.price_updated_at = timezone.now()
                tag.save(update_fields=['last_price', 'price_change', 'price_change_percent', 'price_updated_at'])
                services.record_price_history(tag, quote['price'])
            updated += 1
            for item in get_company_news(tag.ticker, days=NEWS_DAYS):
                if dry_run:
                    news_added += 1
                    continue
                _, created = CompanyNews.objects.get_or_create(
                    tag=tag, url=item['url'],
                    defaults={'headline': item['headline'], 'source': item['source'], 'published_at': item['published_at']},
                )
                if created:
                    news_added += 1
            if not dry_run:
                stale_ids = tag.news.order_by('-published_at').values_list('id', flat=True)[NEWS_KEPT_PER_COMPANY:]
                CompanyNews.objects.filter(id__in=list(stale_ids)).delete()
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}update {updated} compan{"y" if updated == 1 else "ies"}, skip {skipped} (no Finnhub data), '
            f'{prefix}add {news_added} news item(s).'
        ))
