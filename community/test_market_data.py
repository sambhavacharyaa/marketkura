from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import finnhub_client, services
from .models import CompanyNews, PriceHistory, Tag


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
        self.assertEqual(PriceHistory.objects.filter(tag=self.apple).count(), 1)
        self.assertFalse(PriceHistory.objects.filter(tag=self.nepse_only).exists())

    @override_settings(FINNHUB_API_KEY='test-key')
    @mock.patch('community.management.commands.refresh_market_data.get_quote', return_value=None)
    @mock.patch('community.management.commands.refresh_market_data.get_company_news', return_value=[])
    def test_dry_run_writes_nothing(self, mock_news, mock_quote):
        mock_quote.side_effect = lambda ticker: {'price': 227.5, 'change': 1.2, 'change_percent': 0.53} if ticker == 'AAPL' else None
        self.call('--dry-run')
        self.apple.refresh_from_db()
        self.assertIsNone(self.apple.last_price)
        self.assertFalse(CompanyNews.objects.exists())
        self.assertFalse(PriceHistory.objects.exists())

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


class PriceHistoryServiceTests(TestCase):
    def setUp(self):
        self.apple = Tag.objects.create(name='Apple', slug='apple', ticker='AAPL', company_name='Apple Inc.')

    def test_record_price_history_appends_a_point(self):
        services.record_price_history(self.apple, 227.5)
        services.record_price_history(self.apple, 228.1)
        self.assertEqual(list(self.apple.price_history.order_by('recorded_at').values_list('price', flat=True)),
                          [Decimal('227.5'), Decimal('228.1')])

    def test_record_price_history_prunes_beyond_the_cap(self):
        with mock.patch('community.services.PRICE_HISTORY_KEPT_PER_COMPANY', 3):
            for price in range(5):
                services.record_price_history(self.apple, 100 + price)
            self.assertEqual(self.apple.price_history.count(), 3)
            kept = list(self.apple.price_history.order_by('recorded_at').values_list('price', flat=True))
            self.assertEqual(kept, [Decimal('102'), Decimal('103'), Decimal('104')])

    def test_price_chart_points_is_none_below_the_minimum_point_count(self):
        # Below MIN_CHART_POINTS, a normalized chart is just one straight diagonal segment —
        # indistinguishable between any two companies that both moved the same direction. That's
        # literally what "every company's graph looks the same" turned out to be (every company
        # had exactly 2 points). So nothing renders until there's enough real texture to show.
        self.assertIsNone(services.price_chart_points(self.apple))
        for price in (100, 101, 102, 103, 104):  # 5 points, one short of the default minimum (6)
            services.record_price_history(self.apple, price)
        self.assertIsNone(services.price_chart_points(self.apple))

    def test_price_chart_points_normalizes_into_a_0_to_100_square(self):
        for price in (100, 120, 140, 130, 110, 150, 100):
            services.record_price_history(self.apple, price)
        chart = services.price_chart_points(self.apple)
        self.assertEqual(chart['low'], 100)
        self.assertEqual(chart['high'], 150)
        # Lowest price -> y=100 (bottom of the viewBox); highest -> y=0 (top).
        self.assertEqual(chart['line_points'].split()[0], '0.0,100.0')
        self.assertIn('83.33,0.0', chart['line_points'])  # the 150 point, 6th of 7 (index 5/6)
        # The end dot sits at the last point, and the area path drops to the baseline (y=100) at
        # both the first and last x before closing, so it's a filled region, not just a line.
        self.assertEqual(chart['last_x'], 100)
        self.assertEqual(chart['last_y'], 100)
        self.assertTrue(chart['area_path'].startswith('M0.0,100 L0.0,100.0'))
        self.assertTrue(chart['area_path'].endswith('L100.0,100 Z'))

    def test_price_chart_points_hover_points_carry_the_real_price_and_time(self):
        # The hover layer (app.js's setupChartHover) needs the actual observed value at each
        # point, not just its normalized position — that's the whole point of hovering.
        for price in (100, 120, 140, 130, 110, 150, 100):
            services.record_price_history(self.apple, price)
        chart = services.price_chart_points(self.apple)
        hover = chart['hover_points']
        self.assertEqual(len(hover), 7)
        self.assertEqual(hover[0]['price'], 100.0)
        self.assertEqual(hover[0]['x'], 0.0)
        self.assertEqual(hover[5]['price'], 150.0)
        self.assertEqual(hover[5]['x'], 83.33)
        self.assertTrue(hover[0]['time'])  # a real formatted timestamp, not blank

    def test_price_chart_points_is_up_reflects_first_vs_last_point(self):
        for price in (100, 95, 90, 95, 100, 110):
            services.record_price_history(self.apple, price)
        self.assertTrue(services.price_chart_points(self.apple)['is_up'])

    def test_price_chart_points_flat_line_does_not_divide_by_zero(self):
        for _ in range(6):
            services.record_price_history(self.apple, 100)
        chart = services.price_chart_points(self.apple)
        self.assertEqual(set(chart['line_points'].split()[i].split(',')[1] for i in range(6)), {'100.0'})


class CompanyPageMarketDataTests(TestCase):
    def setUp(self):
        self.apple = Tag.objects.create(name='Apple', slug='apple', ticker='AAPL', company_name='Apple Inc.')

    def test_price_is_hidden_when_no_data_has_been_fetched_yet(self):
        response = self.client.get(self.apple.get_absolute_url())
        self.assertNotContains(response, 'class="company-price"')
        self.assertContains(response, 'Not investment advice')

    def test_chart_hidden_with_too_few_history_points(self):
        self.apple.last_price = 227.5
        self.apple.price_change = 1.2
        self.apple.price_change_percent = 0.53
        self.apple.price_updated_at = timezone.now()
        self.apple.save()
        for price in (226, 226.5, 227):  # below MIN_CHART_POINTS
            services.record_price_history(self.apple, price)
        response = self.client.get(self.apple.get_absolute_url())
        self.assertNotContains(response, 'company-chart-svg')
        self.assertContains(response, 'Building price history')

    def test_chart_shown_once_there_is_enough_real_price_history(self):
        self.apple.last_price = 228.1
        self.apple.price_change = 1.2
        self.apple.price_change_percent = 0.53
        self.apple.price_updated_at = timezone.now()
        self.apple.save()
        for price in (225, 226, 227, 227.5, 227.8, 228.1):
            services.record_price_history(self.apple, price)
        response = self.client.get(self.apple.get_absolute_url())
        self.assertContains(response, 'company-chart-svg')
        self.assertContains(response, 'price-up')
        self.assertContains(response, '<polyline')
        self.assertNotContains(response, 'Building price history')

    def test_chart_hover_data_is_embedded_for_the_js_layer(self):
        self.apple.last_price = 228.1
        self.apple.save()
        for price in (225, 226, 227, 227.5, 227.8, 228.1):
            services.record_price_history(self.apple, price)
        response = self.client.get(self.apple.get_absolute_url())
        self.assertContains(response, 'id="company-chart-data"')
        self.assertContains(response, '"price": 228.1')
        self.assertContains(response, 'class="company-chart-crosshair" hidden')
        self.assertContains(response, 'class="company-chart-tooltip" hidden')

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
