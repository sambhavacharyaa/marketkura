from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Category, Comment, Post, Report, Tag, User, VerificationRequest


def make_user(username, days_old=30, **extra):
    user = User.objects.create_user(username=username, email=f'{username}@example.com', password='pass12345', **extra)
    User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=days_old))
    user.refresh_from_db()
    return user


class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.alice = make_user('alice')
        self.bob = make_user('bob')
        self.category = Category.objects.get(slug='nepse')
        self.asset = Tag.objects.create(name='NABIL', slug='nabil', ticker='NABIL', company_name='Nabil Bank Limited')

    def as_user(self, user):
        self.api.force_authenticate(user)

    def post(self, **kwargs):
        defaults = {'title': 'API thread', 'body': 'Body', 'category': self.category, 'user': self.alice}
        defaults.update(kwargs)
        return Post.objects.create(**defaults)

    # --- auth
    def test_signup_returns_token_and_validates(self):
        response = self.api.post('/api/auth/signup', {'username': 'newbie', 'email': 'new@example.com', 'password': 'a-strong-pass-123'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['token'])
        bad = self.api.post('/api/auth/signup', {'username': 'x', 'email': 'ALICE@example.com', 'password': '1'}, format='json')
        self.assertEqual(bad.status_code, 400)
        self.assertIn('email', bad.json()['errors'])

    def test_login_with_username_or_email_and_token_authenticates(self):
        for identifier in ('alice', 'alice@example.com'):
            response = self.api.post('/api/auth/login', {'username': identifier, 'password': 'pass12345'}, format='json')
            self.assertEqual(response.status_code, 200)
        token = response.json()['token']
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(client.post('/api/posts/', {'category': 'nepse', 'title': 'Via token', 'body': 'b'}, format='json').status_code, 201)

    def test_login_failures_lock_out(self):
        for _ in range(5):
            self.assertEqual(self.api.post('/api/auth/login', {'username': 'alice', 'password': 'nope'}, format='json').status_code, 400)
        self.assertEqual(self.api.post('/api/auth/login', {'username': 'alice', 'password': 'pass12345'}, format='json').status_code, 429)

    # --- posts
    def test_public_can_read_but_not_write(self):
        post = self.post()
        self.assertEqual(self.api.get('/api/posts/').json()['count'], 1)
        self.assertEqual(self.api.get(f'/api/posts/{post.pk}/').json()['title'], 'API thread')
        self.assertIn(self.api.post('/api/posts/', {'title': 'x'}, format='json').status_code, (401, 403))
        self.assertIn(self.api.post(f'/api/posts/{post.pk}/comments/', {'body': 'x'}, format='json').status_code, (401, 403))

    def test_create_thesis_and_validation_errors(self):
        self.as_user(self.alice)
        good = self.api.post('/api/posts/', {'category': 'nepse', 'type': 'thesis', 'title': 'Thesis', 'body': 'Why', 'asset_tag': 'NABIL',
                                             'position_type': 'long', 'entry_price': '500', 'time_horizon': 'long', 'tags': ['banking', 'ipo']}, format='json')
        self.assertEqual(good.status_code, 201, good.content)
        data = good.json()
        self.assertEqual((data['asset'], sorted(data['tags'])), ('nabil', ['banking', 'ipo']))
        bad = self.api.post('/api/posts/', {'category': 'nepse', 'type': 'thesis', 'title': 'T', 'body': 'b', 'entry_price': '-5'}, format='json')
        self.assertEqual(bad.status_code, 400)
        self.assertIn('entry_price', bad.json()['errors'])
        unknown = self.api.post('/api/posts/', {'category': 'nope', 'title': 'T', 'body': 'b'}, format='json')
        self.assertEqual(unknown.status_code, 400)

    def test_new_account_limit_applies_to_api_too(self):
        newbie = make_user('newbie', days_old=1)
        self.as_user(newbie)
        for n in range(3):
            self.assertEqual(self.api.post('/api/posts/', {'category': 'nepse', 'title': f'P{n}', 'body': 'b'}, format='json').status_code, 201)
        blocked = self.api.post('/api/posts/', {'category': 'nepse', 'title': 'P4', 'body': 'b'}, format='json')
        self.assertEqual(blocked.status_code, 403)
        self.assertIn('New accounts', blocked.json()['detail'])

    def test_only_verified_members_can_create_ama_via_api(self):
        self.as_user(self.alice)
        payload = {'category': 'nepse', 'type': 'ama', 'title': 'AMA', 'body': 'b', 'ama_ends_at': '2030-01-01T00:00'}
        self.assertEqual(self.api.post('/api/posts/', payload, format='json').status_code, 400)

    def test_filters_by_category_tag_type_and_search(self):
        other = Category.objects.get(slug='market-news')
        tagged = self.post(title='Tagged', asset=self.asset)
        self.post(title='Elsewhere', category=other)
        self.post(title='Thesis one', type='thesis', position_type='long', entry_price=1, time_horizon='long')
        titles = lambda qs: sorted(p['title'] for p in self.api.get('/api/posts/', qs).json()['results'])
        self.assertEqual(titles({'category': 'market-news'}), ['Elsewhere'])
        self.assertEqual(titles({'tag': 'nabil'}), ['Tagged'])
        self.assertEqual(titles({'type': 'thesis'}), ['Thesis one'])
        self.assertEqual(titles({'q': 'elsewh'}), ['Elsewhere'])
        del tagged

    def test_tag_posts_endpoint_returns_company_page_data(self):
        self.post(title='About Nabil', asset=self.asset)
        data = self.api.get('/api/tags/nabil/posts').json()
        self.assertEqual(data['tag']['ticker'], 'NABIL')
        self.assertEqual([p['title'] for p in data['results']], ['About Nabil'])
        self.assertEqual(self.api.get('/api/tags/missing/posts').status_code, 404)

    # --- comments, votes
    def test_comment_threading_and_upvote(self):
        post = self.post()
        self.as_user(self.bob)
        top = self.api.post(f'/api/posts/{post.pk}/comments/', {'body': 'first'}, format='json')
        self.assertEqual(top.status_code, 201)
        reply = self.api.post(f'/api/posts/{post.pk}/comments/', {'body': 'reply', 'parent': top.json()['id']}, format='json')
        self.assertEqual(reply.json()['parent'], top.json()['id'])
        self.assertEqual(self.api.get(f'/api/posts/{post.pk}/comments/').json()['count'], 2)
        self.assertEqual(self.api.post(f'/api/posts/{post.pk}/upvote').json(), {'voted': True, 'upvotes': 1})
        self.assertEqual(self.api.post(f'/api/posts/{post.pk}/upvote').json(), {'voted': False, 'upvotes': 0})
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.karma_score, 0)

    def test_self_upvote_and_locked_thread_rejected(self):
        post = self.post()
        self.as_user(self.alice)
        self.assertEqual(self.api.post(f'/api/posts/{post.pk}/upvote').status_code, 400)
        post.is_locked = True
        post.save()
        self.as_user(self.bob)
        self.assertEqual(self.api.post(f'/api/posts/{post.pk}/comments/', {'body': 'x'}, format='json').status_code, 403)

    def test_shadow_banned_and_removed_content_hidden_from_api(self):
        ghost = make_user('ghost', is_shadow_banned=True)
        hidden = self.post(user=ghost, title='Ghost')
        removed = self.post(title='Removed', is_removed=True)
        self.assertEqual(self.api.get('/api/posts/').json()['count'], 0)
        self.assertEqual(self.api.get(f'/api/posts/{hidden.pk}/').status_code, 404)
        self.assertEqual(self.api.get(f'/api/posts/{removed.pk}/').status_code, 404)
        self.as_user(ghost)
        self.assertEqual(self.api.get('/api/posts/').json()['count'], 1)

    # --- users, verification, reports
    def test_user_endpoint(self):
        data = self.api.get('/api/users/alice/').json()
        self.assertEqual((data['username'], data['is_verified']), ('alice', False))
        self.assertNotIn('email', data)
        self.assertEqual(self.api.get('/api/users/nobody/').status_code, 404)

    def test_verification_apply_once(self):
        self.as_user(self.alice)
        payload = {'requested_type': 'Verified Analyst', 'full_name': 'A', 'application_reason': 'r', 'areas_of_expertise': 'e', 'experience': 'x', 'supporting_information': 's'}
        self.assertEqual(self.api.post('/api/verification/apply', payload, format='json').status_code, 201)
        self.assertEqual(self.api.post('/api/verification/apply', payload, format='json').status_code, 409)
        self.assertEqual(VerificationRequest.objects.count(), 1)

    def test_report_post_and_comment_via_api(self):
        post = self.post()
        comment = Comment.objects.create(post=post, user=self.alice, body='c')
        self.as_user(self.bob)
        self.assertEqual(self.api.post('/api/reports/', {'post': post.pk, 'category': 'spam'}, format='json').status_code, 201)
        self.assertEqual(self.api.post('/api/reports/', {'post': post.pk, 'category': 'spam'}, format='json').status_code, 400)
        self.assertEqual(self.api.post('/api/reports/', {'comment': comment.pk, 'category': 'hype'}, format='json').status_code, 201)
        self.assertEqual(self.api.post('/api/reports/', {'category': 'spam'}, format='json').status_code, 400)
        self.assertEqual(Report.objects.count(), 2)
        self.as_user(self.alice)
        self.assertEqual(self.api.post('/api/reports/', {'post': post.pk, 'category': 'spam'}, format='json').status_code, 400)

    def test_categories_endpoint(self):
        slugs = {c['slug'] for c in self.api.get('/api/categories/').json()}
        self.assertIn('nepse', slugs)
