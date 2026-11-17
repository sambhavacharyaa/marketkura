from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import finnhub_client
from .models import CompanyNews, Tag


class FinnhubClientTests(TestCase):
    @override_settings(FINNHUB_API_KEY='')
    def test_get_quote_returns_none_without_an_api_key(self):
        self.assertIsNone(finnhub_client.get_quote('AAPL'))

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.finnhub_client.requests.get')
    def test_get_quote_parses_a_successful_response(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: {'c': 227.5, 'd': 1.2, 'dp': 0.53})
        mock_get.return_value.raise_for_status = mock.Mock()
        quote = finnhub_client.get_quote('AAPL')
        self.assertEqual(quote, {'price': 227.5, 'change': 1.2, 'change_percent': 0.53})

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.finnhub_client.requests.get')
    def test_get_quote_treats_an_all_zero_response_as_unknown_symbol(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: {'c': 0, 'd': 0, 'dp': 0})
        mock_get.return_value.raise_for_status = mock.Mock()
        self.assertIsNone(finnhub_client.get_quote('NOTASYMBOL'))

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.finnhub_client.requests.get')
    def test_get_quote_returns_none_on_a_network_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError('boom')
        self.assertIsNone(finnhub_client.get_quote('AAPL'))

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.finnhub_client.requests.get')
    def test_get_company_news_parses_items_and_skips_incomplete_ones(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [
            {'headline': 'Apple ships a thing', 'url': 'https://example.com/1', 'source': 'Reuters', 'datetime': 1700000000},
            {'headline': '', 'url': 'https://example.com/2', 'source': 'Reuters', 'datetime': 1700000001},
            {'headline': 'Missing url', 'url': '', 'source': 'Reuters', 'datetime': 1700000002},
        ])
        mock_get.return_value.raise_for_status = mock.Mock()
        items = finnhub_client.get_company_news('AAPL')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['headline'], 'Apple ships a thing')
        self.assertEqual(items[0]['published_at'], datetime.fromtimestamp(1700000000, tz=dt_timezone.utc))


class RefreshMarketDataCommandTests(TestCase):
    def setUp(self):
        self.apple = Tag.objects.create(name='Apple', slug='apple', ticker='AAPL', company_name='Apple Inc.')
        self.nepse_only = Tag.objects.create(name='NABIL', slug='nabil', ticker='NABIL', company_name='Nabil Bank')

    def call(self, *args):
        out = StringIO()
        call_command('refresh_market_data', *args, stdout=out)
        return out.getvalue()

    @override_settings(FINNHUB_API_KEY='')
    def test_does_nothing_without_an_api_key(self):
        out = self.call()
        self.assertIn('not set', out)
        self.apple.refresh_from_db()
        self.assertIsNone(self.apple.last_price)

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.management.commands.refresh_market_data.get_company_news', return_value=[])
    @mock.patch('community.management.commands.refresh_market_data.get_quote')
    def test_updates_price_fields_for_a_recognized_ticker_and_skips_the_rest(self, mock_quote, mock_news):
        mock_quote.side_effect = lambda ticker: {'price': 227.5, 'change': 1.2, 'change_percent': 0.53} if ticker == 'AAPL' else None
        out = self.call()
        self.apple.refresh_from_db()
        self.assertEqual(self.apple.last_price, Decimal('227.5'))
        self.assertEqual(self.apple.price_change, Decimal('1.2'))
        self.assertIsNotNone(self.apple.price_updated_at)
        self.nepse_only.refresh_from_db()
        self.assertIsNone(self.nepse_only.last_price)
        self.assertIn('update 1 compan', out)
        self.assertIn('skip 1', out)

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.management.commands.refresh_market_data.get_quote', return_value=None)
    @mock.patch('community.management.commands.refresh_market_data.get_company_news', return_value=[])
    def test_dry_run_writes_nothing(self, mock_news, mock_quote):
        mock_quote.side_effect = lambda ticker: {'price': 227.5, 'change': 1.2, 'change_percent': 0.53} if ticker == 'AAPL' else None
        self.call('--dry-run')
        self.apple.refresh_from_db()
        self.assertIsNone(self.apple.last_price)
        self.assertFalse(CompanyNews.objects.exists())

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.management.commands.refresh_market_data.get_quote')
    @mock.patch('community.management.commands.refresh_market_data.get_company_news')
    def test_news_items_are_added_once_and_not_duplicated_on_rerun(self, mock_news, mock_quote):
        mock_quote.return_value = {'price': 227.5, 'change': 1.2, 'change_percent': 0.53}
        mock_news.return_value = [
            {'headline': 'Headline one', 'url': 'https://example.com/1', 'source': 'Reuters',
             'published_at': datetime.fromtimestamp(1700000000, tz=dt_timezone.utc)},
        ]
        self.call()
        self.call()
        self.assertEqual(CompanyNews.objects.filter(tag=self.apple).count(), 1)

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.management.commands.refresh_market_data.get_quote')
    @mock.patch('community.management.commands.refresh_market_data.get_company_news')
    def test_only_the_most_recent_news_items_are_kept_per_company(self, mock_news, mock_quote):
        mock_quote.return_value = {'price': 227.5, 'change': 1.2, 'change_percent': 0.53}
        mock_news.return_value = [
            {'headline': f'Headline {i}', 'url': f'https://example.com/{i}', 'source': 'Reuters',
             'published_at': datetime.fromtimestamp(1700000000 + i, tz=dt_timezone.utc)}
            for i in range(20)
        ]
        self.call()
        self.assertEqual(CompanyNews.objects.filter(tag=self.apple).count(), 15)
        kept_urls = set(CompanyNews.objects.filter(tag=self.apple).values_list('url', flat=True))
        self.assertIn('https://example.com/19', kept_urls)
        self.assertNotIn('https://example.com/0', kept_urls)


class CompanyPageMarketDataTests(TestCase):
    def setUp(self):
        self.apple = Tag.objects.create(name='Apple', slug='apple', ticker='AAPL', company_name='Apple Inc.')

    def test_price_is_hidden_when_no_data_has_been_fetched_yet(self):
        response = self.client.get(self.apple.get_absolute_url())
        self.assertNotContains(response, 'class="company-price"')
        self.assertContains(response, 'Not investment advice')

    def test_price_shows_once_fetched_with_correct_up_down_color_class(self):
        self.apple.last_price = 227.5
        self.apple.price_change = 1.2
        self.apple.price_change_percent = 0.53
        self.apple.price_updated_at = timezone.now()
        self.apple.save()
        response = self.client.get(self.apple.get_absolute_url())
        self.assertContains(response, 'class="company-price"')
        self.assertContains(response, 'price-up')
        self.assertContains(response, '227.5')

    def test_negative_change_gets_the_down_color_class(self):
        self.apple.last_price = 227.5
        self.apple.price_change = -1.2
        self.apple.price_change_percent = -0.53
        self.apple.price_updated_at = timezone.now()
        self.apple.save()
        response = self.client.get(self.apple.get_absolute_url())
        self.assertContains(response, 'price-down')

    def test_news_list_renders_when_present(self):
        CompanyNews.objects.create(
            tag=self.apple, headline='Apple news headline', url='https://example.com/1', source='Reuters',
            published_at=timezone.now(),
        )
        response = self.client.get(self.apple.get_absolute_url())
        self.assertContains(response, 'Apple news headline')
        self.assertContains(response, 'https://example.com/1')

    def test_empty_state_shown_when_no_news_yet(self):
        response = self.client.get(self.apple.get_absolute_url())
        self.assertContains(response, 'No news fetched for this company yet.')

    def test_companies_list_shows_the_price_badge_too(self):
        self.apple.last_price = 227.5
        self.apple.price_change_percent = 0.53
        self.apple.save()
        response = self.client.get(reverse('companies'))
        self.assertContains(response, 'company-price-inline')
