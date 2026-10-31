import io
import tempfile
import time
from datetime import timedelta
from unittest import mock, skipUnless

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (Category, CategoryFollow, Comment, CommentVote, ContactMessage, NewsPost, Notification, Post,
                     PostTag, Report, StartupProfile, Tag, User, VerificationRequest)
from .services import pump_watch, recalculate_karma


def make_user(username, days_old=30, **extra):
    """A member whose account is old enough to be outside the new-account limits."""
    user = User.objects.create_user(username=username, email=f'{username}@example.com', password='pass12345', **extra)
    User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=days_old))
    user.refresh_from_db()
    return user


def make_test_image(name='test.jpg'):
    """A minimal real JPEG, not just bytes with a .jpg name — Django's ImageField validates the
    file is actually decodable as an image, so a fake/empty file fails form validation."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (40, 40), (10, 90, 60)).save(buf, format='JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


class BaseCase(TestCase):
    def setUp(self):
        cache.clear()
        self.alice = make_user('alice')
        self.bob = make_user('bob')
        self.staff = make_user('mod', is_staff=True)
        self.category = Category.objects.get(slug='nepse')
        self.asset = Tag.objects.create(name='NABIL', slug='nabil', ticker='NABIL', company_name='Nabil Bank Limited')

    def post(self, user=None, **kwargs):
        defaults = {'title': 'A thread', 'body': 'Body text', 'category': self.category, 'user': user or self.alice}
        defaults.update(kwargs)
        return Post.objects.create(**defaults)

    def login(self, user):
        self.client.force_login(user)


class SeedTests(BaseCase):
    def test_blueprint_categories_are_seeded(self):
        slugs = set(Category.objects.values_list('slug', flat=True))
        self.assertTrue({'nepse', 'global-markets', 'startups-founders', 'personal-finance', 'trading-strategy', 'market-news'} <= slugs)


class AuthTests(BaseCase):
    def test_login_with_username_or_email(self):
        self.assertTrue(self.client.login(username='alice', password='pass12345'))
        self.client.logout()
        self.assertTrue(self.client.login(username='ALICE@example.com', password='pass12345'))

    def test_login_view_accepts_email(self):
        response = self.client.post(reverse('login'), {'username': 'alice@example.com', 'password': 'pass12345'})
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_repeated_failures_lock_out_then_success_is_blocked_until_expiry(self):
        for _ in range(5):
            self.assertEqual(self.client.post(reverse('login'), {'username': 'alice', 'password': 'wrong'}).status_code, 200)
        locked = self.client.post(reverse('login'), {'username': 'alice', 'password': 'pass12345'})
        self.assertEqual(locked.status_code, 429)
        self.assertFalse(locked.wsgi_request.user.is_authenticated)
        # A different account from the same address is not locked by the per-account counter.
        self.assertEqual(self.client.post(reverse('login'), {'username': 'bob', 'password': 'pass12345'}).status_code, 302)

    def test_successful_login_resets_failure_counter(self):
        for _ in range(4):
            self.client.post(reverse('login'), {'username': 'alice', 'password': 'wrong'})
        self.client.post(reverse('login'), {'username': 'alice', 'password': 'pass12345'})
        self.client.logout()
        self.assertEqual(self.client.post(reverse('login'), {'username': 'alice', 'password': 'wrong'}).status_code, 200)

    def test_signup_rejects_duplicate_email_case_insensitively(self):
        response = self.client.post(reverse('signup'), {'username': 'newbie', 'email': 'ALICE@example.com', 'password1': 'a-strong-pass-123', 'password2': 'a-strong-pass-123'})
        self.assertContains(response, 'already exists')
        self.assertFalse(User.objects.filter(username='newbie').exists())

    def test_signup_rejects_non_ascii_lookalike_usernames(self):
        # "аdmin" starts with a Cyrillic а (U+0430), not the Latin "a" — visually identical
        # to "admin" but a distinct string, so Django's default Unicode username field would
        # happily register it alongside the real thing. That's the impersonation vector this
        # closes.
        response = self.client.post(reverse('signup'), {'username': 'аdmin', 'email': 'lookalike@example.com', 'password1': 'a-strong-pass-123', 'password2': 'a-strong-pass-123'})
        self.assertContains(response, 'English letters')
        self.assertFalse(User.objects.filter(username='аdmin').exists())

    def test_signup_rejects_reserved_names_case_insensitively(self):
        for name in ['admin', 'Admin', 'MARKETKURAA', 'root', 'Support']:
            response = self.client.post(reverse('signup'), {'username': name, 'email': f'{name}@example.com', 'password1': 'a-strong-pass-123', 'password2': 'a-strong-pass-123'})
            self.assertContains(response, 'reserved', msg_prefix=f'expected {name!r} to be rejected')
            self.assertFalse(User.objects.filter(username__iexact=name).exists())

    def test_signup_accepts_ordinary_ascii_usernames(self):
        response = self.client.post(reverse('signup'), {'username': 'trader_99', 'email': 'trader99@example.com', 'password1': 'a-strong-pass-123', 'password2': 'a-strong-pass-123', 'agree_to_terms': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='trader_99').exists())

    def test_signup_requires_agreeing_to_terms(self):
        response = self.client.post(reverse('signup'), {'username': 'noagree', 'email': 'noagree@example.com', 'password1': 'a-strong-pass-123', 'password2': 'a-strong-pass-123'})
        self.assertContains(response, 'You must agree')
        self.assertFalse(User.objects.filter(username='noagree').exists())

    def signup_payload(self, **overrides):
        data = {'username': 'honeytest', 'email': 'honeytest@example.com', 'password1': 'a-strong-pass-123', 'password2': 'a-strong-pass-123', 'agree_to_terms': 'on'}
        data.update(overrides)
        return data

    def test_signup_honeypot_field_blocks_registration(self):
        response = self.client.post(reverse('signup'), self.signup_payload(website='http://spam.example'))
        self.assertContains(response, 'Please try again')
        self.assertFalse(User.objects.filter(username='honeytest').exists())

    def test_signup_submitted_too_fast_is_blocked(self):
        response = self.client.post(reverse('signup'), self.signup_payload(form_rendered_at=time.time()))
        self.assertContains(response, 'Please try again')
        self.assertFalse(User.objects.filter(username='honeytest').exists())

    def test_signup_succeeds_with_empty_honeypot_and_a_plausible_delay(self):
        response = self.client.post(reverse('signup'), self.signup_payload(website='', form_rendered_at=time.time() - 10))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='honeytest').exists())

    def test_signup_without_turnstile_keys_configured_skips_the_check(self):
        # Default test settings have no TURNSTILE_SECRET_KEY — this is also what local dev looks
        # like without Cloudflare keys, and signup must keep working.
        response = self.client.post(reverse('signup'), self.signup_payload(form_rendered_at=time.time() - 10))
        self.assertEqual(response.status_code, 302)

    @override_settings(TURNSTILE_SECRET_KEY='test-secret-key')
    def test_signup_blocked_without_a_turnstile_token_when_configured(self):
        response = self.client.post(reverse('signup'), self.signup_payload(form_rendered_at=time.time() - 10))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='honeytest').exists())

    @override_settings(TURNSTILE_SECRET_KEY='test-secret-key')
    def test_signup_succeeds_when_turnstile_verifies(self):
        fake_response = mock.Mock()
        fake_response.read.return_value = b'{"success": true}'
        fake_response.__enter__ = mock.Mock(return_value=fake_response)
        fake_response.__exit__ = mock.Mock(return_value=False)
        with mock.patch('community.services.urllib.request.urlopen', return_value=fake_response):
            response = self.client.post(reverse('signup'), self.signup_payload(form_rendered_at=time.time() - 10, **{'cf-turnstile-response': 'a-real-looking-token'}))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='honeytest').exists())

    @override_settings(TURNSTILE_SECRET_KEY='test-secret-key')
    def test_signup_blocked_when_turnstile_rejects_the_token(self):
        fake_response = mock.Mock()
        fake_response.read.return_value = b'{"success": false}'
        fake_response.__enter__ = mock.Mock(return_value=fake_response)
        fake_response.__exit__ = mock.Mock(return_value=False)
        with mock.patch('community.services.urllib.request.urlopen', return_value=fake_response):
            response = self.client.post(reverse('signup'), self.signup_payload(form_rendered_at=time.time() - 10, **{'cf-turnstile-response': 'a-bad-token'}))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='honeytest').exists())

    def test_signup_is_rate_limited_per_address(self):
        with override_settings(SIGNUP_MAX_PER_HOUR=2):
            for n in range(3):
                self.client.logout()
                response = self.client.post(reverse('signup'), {'username': f'user{n}', 'email': f'user{n}@example.com', 'password1': 'a-strong-pass-123', 'password2': 'a-strong-pass-123', 'agree_to_terms': 'on'})
            self.assertEqual(response.status_code, 429)

    def test_password_reset_sends_email_and_pages_render(self):
        self.assertEqual(self.client.get(reverse('password_reset')).status_code, 200)
        self.client.post(reverse('password_reset'), {'email': 'alice@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/accounts/reset/', mail.outbox[0].body)
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse('password_change')).status_code, 200)

    def test_settings_updates_profile_and_rejects_taken_email(self):
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse('settings')).status_code, 200)
        self.client.post(reverse('settings'), {'email': 'alice2@example.com', 'bio': 'Long-term investor'})
        self.alice.refresh_from_db()
        self.assertEqual((self.alice.email, self.alice.bio), ('alice2@example.com', 'Long-term investor'))
        response = self.client.post(reverse('settings'), {'email': 'bob@example.com', 'bio': ''})
        self.assertContains(response, 'already exists')

    @override_settings(GOOGLE_LOGIN_ENABLED=True)
    def test_google_login_button_only_when_configured(self):
        self.assertContains(self.client.get(reverse('login')), 'Continue with Google')

    def test_google_login_button_hidden_by_default(self):
        self.assertNotContains(self.client.get(reverse('login')), 'Continue with Google')

    def test_google_login_url_is_wired(self):
        self.assertEqual(reverse('google_login'), '/auth/google/login/')

    def test_mobile_bottom_nav_plus_button_sends_anonymous_users_to_login_with_next(self):
        page = self.client.get(reverse('home')).content.decode()
        bottom_nav = page[page.index('id="bottom-nav"'):]
        plus_link = bottom_nav[bottom_nav.index('bottom-nav-new'):bottom_nav.index('</a>', bottom_nav.index('bottom-nav-new'))]
        self.assertIn(f'href="{reverse("login")}?next={reverse("create_post")}"', plus_link)
        self.assertIn('aria-label="Create post"', plus_link)
        self.assertNotIn('aria-label="Log in"', plus_link)

    def test_login_page_shows_a_create_post_specific_message_when_that_is_the_destination(self):
        response = self.client.get(reverse('login'), {'next': reverse('create_post')})
        self.assertContains(response, 'Log in to create a post.')
        response = self.client.get(reverse('login'))
        self.assertNotContains(response, 'Log in to create a post.')
        self.assertContains(response, 'Welcome back')

    def test_login_link_is_present_for_anonymous_mobile_users(self):
        # The header's "Log in" link must exist in the markup (CSS alone decides whether it's
        # visible at a given width) and is distinct from the bottom-nav "+" button.
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn('class="hdr-auth-links"', page)
        self.assertIn(f'class="hdr-link" href="{reverse("login")}"', page)


class SafeRedirectTests(BaseCase):
    def test_next_parameter_cannot_redirect_off_site(self):
        post = self.post(user=self.bob)
        self.login(self.alice)
        response = self.client.post(reverse('toggle_post_vote', args=[post.pk]), {'next': 'https://evil.example/phish'})
        self.assertEqual(response.url, post.get_absolute_url())
        response = self.client.post(reverse('toggle_follow', args=['bob']), {'next': '//evil.example'})
        self.assertEqual(response.url, reverse('profile', args=['bob']))

    def test_same_site_next_is_honoured(self):
        post = self.post(user=self.bob)
        self.login(self.alice)
        response = self.client.post(reverse('toggle_post_vote', args=[post.pk]), {'next': '/posts/'})
        self.assertEqual(response.url, '/posts/')


class PostingRuleTests(BaseCase):
    def payload(self, **overrides):
        data = {'category': self.category.pk, 'type': 'discussion', 'title': 'Hello', 'body': 'World'}
        data.update(overrides)
        return data

    def test_new_accounts_limited_to_three_posts_a_day(self):
        newbie = make_user('newbie', days_old=1)
        self.login(newbie)
        for n in range(3):
            self.assertEqual(self.client.post(reverse('create_post'), self.payload(title=f'Post {n}')).status_code, 302)
        blocked = self.client.post(reverse('create_post'), self.payload(title='One too many'))
        self.assertEqual(blocked.status_code, 403)
        self.assertContains(blocked, 'New accounts can publish 3 posts a day', status_code=403)
        self.assertEqual(Post.objects.filter(user=newbie).count(), 3)

    def test_limit_lifts_after_seven_days_and_staff_are_exempt(self):
        for n in range(4):
            self.login(self.alice)
            self.assertEqual(self.client.post(reverse('create_post'), self.payload(title=f'Old {n}')).status_code, 302)
        self.login(self.staff)
        self.assertEqual(self.client.post(reverse('create_post'), self.payload(title='Staff')).status_code, 302)

    def test_high_trust_category_needs_karma_or_verification(self):
        gated = Category.objects.create(name='Pro', slug='pro', min_karma=5)
        self.login(self.alice)
        self.assertEqual(self.client.post(reverse('create_post'), self.payload(category=gated.pk)).status_code, 403)
        self.alice.karma_score = 5
        self.alice.save()
        self.assertEqual(self.client.post(reverse('create_post'), self.payload(category=gated.pk)).status_code, 302)

    def test_verified_only_category(self):
        gated = Category.objects.create(name='Analysts', slug='analysts', requires_verified=True)
        self.login(self.alice)
        self.assertEqual(self.client.post(reverse('create_post'), self.payload(category=gated.pk)).status_code, 403)
        self.alice.is_verified = True
        self.alice.save()
        self.assertEqual(self.client.post(reverse('create_post'), self.payload(category=gated.pk)).status_code, 302)

    def test_tags_create_topic_tags_and_feed_company_page(self):
        self.login(self.alice)
        self.client.post(reverse('create_post'), self.payload(title='IPO season', tags='#IPO, banking, ipo'))
        post = Post.objects.get(title='IPO season')
        self.assertEqual(set(PostTag.objects.filter(post=post).values_list('tag__slug', flat=True)), {'ipo', 'banking'})
        self.assertFalse(Tag.objects.get(slug='ipo').is_company)
        page = self.client.get(reverse('company_detail', args=['ipo']))
        self.assertContains(page, 'IPO season')

    def test_company_page_counts_each_comment_once_with_tags_and_asset(self):
        post = self.post(asset=self.asset, title='Counted once')
        PostTag.objects.create(post=post, tag=self.asset)
        for n in range(3):
            Comment.objects.create(post=post, user=self.bob, body=f'c{n}')
        response = self.client.get(self.asset.get_absolute_url())
        self.assertContains(response, '3 replies')
        self.assertEqual(response.context['stats']['total'], 1)

    def test_company_topic_tags_excluded_from_company_directory(self):
        Tag.objects.create(name='ipo', slug='ipo', is_company=False)
        self.assertNotContains(self.client.get(reverse('companies')), '/company/ipo/')
        self.assertContains(self.client.get(reverse('companies')), 'Nabil Bank Limited')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PostImageTests(BaseCase):
    def payload(self, **overrides):
        data = {'category': self.category.pk, 'type': 'discussion', 'title': 'Hello', 'body': 'World'}
        data.update(overrides)
        return data

    def test_post_can_be_created_with_an_image(self):
        self.login(self.alice)
        response = self.client.post(reverse('create_post'), self.payload(image=make_test_image()))
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title='Hello')
        self.assertTrue(post.image)
        detail = self.client.get(post.get_absolute_url())
        self.assertContains(detail, 'post-image')
        self.assertContains(detail, post.image.url)

    def test_image_is_optional(self):
        self.login(self.alice)
        response = self.client.post(reverse('create_post'), self.payload())
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title='Hello')
        self.assertFalse(post.image)
        self.assertNotContains(self.client.get(post.get_absolute_url()), 'post-image')

    def test_oversized_image_is_rejected(self):
        # Goes through PostForm directly rather than the test client: the client re-encodes the
        # file as real multipart bytes, so a manually-inflated .size on the local object never
        # reaches the server — only the actual (tiny) byte count would. The form's clean_image is
        # what reads .size, so it's the right unit to exercise this at.
        from community.forms import POST_IMAGE_MAX_BYTES, PostForm
        big = make_test_image()
        big.size = POST_IMAGE_MAX_BYTES + 1
        form = PostForm(data=self.payload(), files={'image': big}, user=self.alice)
        self.assertFalse(form.is_valid())
        self.assertIn('Please upload an image under 5 MB.', form.errors['image'])

    def test_feed_card_shows_an_image_thumbnail(self):
        post = self.post(image=make_test_image())
        self.assertContains(self.client.get(reverse('home')), 'feed-image')

    def test_owner_can_replace_the_image_when_editing(self):
        post = self.post(user=self.alice, image=make_test_image('first.jpg'))
        self.login(self.alice)
        response = self.client.post(
            reverse('edit_post', args=[post.pk]),
            self.payload(title=post.title, body=post.body, image=make_test_image('second.jpg')),
        )
        self.assertEqual(response.status_code, 302)
        post.refresh_from_db()
        self.assertIn('second', post.image.name)


class UrlTests(BaseCase):
    def test_post_url_is_slug_based_and_canonical(self):
        post = self.post(title='Why Nabil Bank is my top pick!')
        self.assertEqual(post.get_absolute_url(), f'/post/why-nabil-bank-is-my-top-pick-{post.pk}/')
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)

    def test_id_only_and_stale_slugs_redirect_permanently(self):
        post = self.post(title='Old title')
        response = self.client.get(f'/post/{post.pk}/')
        self.assertEqual((response.status_code, response.url), (301, post.get_absolute_url()))
        old_url = post.get_absolute_url()
        post.title = 'New title'
        post.save()
        response = self.client.get(old_url)
        self.assertEqual((response.status_code, response.url), (301, post.get_absolute_url()))

    def test_posts_redirects_permanently_to_home_with_filters_preserved(self):
        # /posts/ used to render its own unfiltered listing — same apply_post_filters(), same
        # post_filters.html form as the home feed, none of home's own chrome. Now it 301s to home,
        # carrying the query string through unchanged (same filter param names on both).
        response = self.client.get(reverse('posts'))
        self.assertEqual((response.status_code, response.url), (301, reverse('home')))
        response = self.client.get(reverse('posts'), {'type': 'thesis', 'sort': 'discussed'})
        self.assertEqual((response.status_code, response.url), (301, f'{reverse("home")}?type=thesis&sort=discussed'))

    def test_posts_link_is_gone_from_the_nav_now_that_it_redirects_to_home(self):
        page = self.client.get(reverse('home')).content.decode()
        self.assertNotIn(f'href="{reverse("posts")}"', page)

    def test_unknown_or_garbled_post_urls_404(self):
        self.assertEqual(self.client.get('/post/nope/').status_code, 404)
        self.assertEqual(self.client.get('/post/nope-999999/').status_code, 404)

    def test_nepali_titles_get_unicode_slugs(self):
        post = self.post(title='नेप्से बजार विश्लेषण')
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)

    def test_company_urls_use_slug_and_legacy_ticker_redirects(self):
        self.assertEqual(self.asset.get_absolute_url(), '/company/nabil/')
        self.assertEqual(self.client.get('/company/NABIL/').status_code, 301)
        response = self.client.get('/companies/NABIL/')
        self.assertEqual((response.status_code, response.url), (301, '/company/nabil/'))

    def test_seo_markup_on_post_and_company_pages(self):
        post = self.post(title='SEO check', asset=self.asset)
        html = self.client.get(post.get_absolute_url()).content.decode()
        self.assertIn('DiscussionForumPosting', html)
        self.assertIn(f'<link rel="canonical" href="http://testserver{post.get_absolute_url()}">', html)
        company = self.client.get(self.asset.get_absolute_url()).content.decode()
        self.assertIn('og:title', company)
        self.assertIn('Discussions, Theses', company)

    def test_sitemap_and_robots(self):
        post = self.post(title='Indexed post', asset=self.asset)
        hidden = self.post(title='Removed post', is_removed=True)
        sitemap = self.client.get(reverse('sitemap')).content.decode()
        self.assertIn(post.get_absolute_url(), sitemap)
        self.assertIn('/company/nabil/', sitemap)
        self.assertIn('/category/nepse/', sitemap)
        self.assertNotIn(hidden.get_absolute_url(), sitemap)
        robots = self.client.get(reverse('robots'))
        self.assertContains(robots, 'Sitemap: http://testserver/sitemap.xml')
        self.assertContains(robots, 'Disallow: /moderation/')

    def test_public_read_access_needs_no_login(self):
        post = self.post()
        for url in ('/', self.category.get_absolute_url(), post.get_absolute_url(), '/companies/', '/startups/',
                    '/guidelines/', '/disclaimer/', '/about/', reverse('profile', args=['alice'])):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        # /posts/ redirects (no login needed either) rather than rendering its own 200 - see
        # test_posts_redirects_permanently_to_home_with_filters below.
        self.assertEqual(self.client.get('/posts/').status_code, 301)

    def test_disclaimer_is_shown_site_wide(self):
        self.assertContains(self.client.get('/'), 'not investment advice')
        self.assertContains(self.client.get(self.post().get_absolute_url()), 'not investment advice')

    def test_privacy_and_terms_pages_render_and_are_linked_and_indexed(self):
        self.assertEqual(self.client.get(reverse('privacy')).status_code, 200)
        self.assertEqual(self.client.get(reverse('terms')).status_code, 200)
        home = self.client.get('/').content.decode()
        self.assertIn(f'href="{reverse("privacy")}"', home)
        self.assertIn(f'href="{reverse("terms")}"', home)
        login_page = self.client.get(reverse('login')).content.decode()
        self.assertIn(f'href="{reverse("privacy")}"', login_page)
        self.assertIn(f'href="{reverse("terms")}"', login_page)
        sitemap = self.client.get(reverse('sitemap')).content.decode()
        self.assertIn(reverse('privacy'), sitemap)
        self.assertIn(reverse('terms'), sitemap)


class CommentTests(BaseCase):
    def test_threaded_replies_render_nested_and_notify(self):
        post = self.post()
        self.login(self.bob)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'top level'})
        top = Comment.objects.get()
        self.login(self.alice)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'reply one', 'parent_comment': top.pk})
        reply = Comment.objects.get(body='reply one')
        self.login(self.bob)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'reply two deep', 'parent_comment': reply.pk})
        self.assertEqual(Comment.objects.get(body='reply two deep').parent_comment, reply)
        page = self.client.get(post.get_absolute_url())
        roots = page.context['comments']
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].children[0].children[0].body, 'reply two deep')
        self.assertContains(page, 'reply two deep')
        self.assertTrue(Notification.objects.filter(recipient=self.bob, notification_type='reply').exists())

    def test_reply_parent_must_belong_to_same_post(self):
        one, two = self.post(title='One'), self.post(title='Two')
        foreign = Comment.objects.create(post=two, user=self.bob, body='elsewhere')
        self.login(self.alice)
        response = self.client.post(reverse('add_comment', args=[one.pk]), {'body': 'x', 'parent_comment': foreign.pk})
        self.assertEqual(response.status_code, 404)

    def test_comment_markdown_is_rendered_but_scripts_are_stripped(self):
        post = self.post()
        Comment.objects.create(post=post, user=self.bob, body='**bold** <script>alert(1)</script> <img src=x onerror=alert(2)> [bad](javascript:alert(3)) [ok](https://example.com)')
        html = self.client.get(post.get_absolute_url()).content.decode()
        self.assertIn('<strong>bold</strong>', html)
        self.assertNotIn('<script>alert', html)
        self.assertNotIn('onerror', html)
        self.assertNotIn('javascript:', html)
        self.assertIn('href="https://example.com"', html)
        self.assertIn('rel="nofollow ugc noopener noreferrer"', html)

    def test_post_body_html_is_escaped(self):
        post = self.post(body='<script>alert("x")</script> plain')
        html = self.client.get(post.get_absolute_url()).content.decode()
        self.assertNotIn('<script>alert("x")', html)

    def test_edit_and_delete_only_by_author(self):
        post = self.post()
        comment = Comment.objects.create(post=post, user=self.bob, body='mine')
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse('edit_comment', args=[comment.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('delete_comment', args=[comment.pk])).status_code, 403)
        self.login(self.bob)
        self.client.post(reverse('edit_comment', args=[comment.pk]), {'body': 'edited'})
        comment.refresh_from_db()
        self.assertEqual(comment.body, 'edited')
        Comment.objects.create(post=post, user=self.alice, body='child', parent_comment=comment)
        self.client.post(reverse('delete_comment', args=[comment.pk]))
        page = self.client.get(post.get_absolute_url())
        self.assertContains(page, '[This comment was removed]')
        self.assertNotContains(page, 'edited')
        self.assertContains(page, 'child')  # replies survive

    def test_locked_thread_blocks_comments(self):
        post = self.post(is_locked=True)
        self.login(self.bob)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'nope'})
        self.assertEqual(Comment.objects.count(), 0)
        self.assertContains(self.client.get(post.get_absolute_url()), 'This thread is locked')

    def test_new_accounts_have_a_comment_limit(self):
        newbie = make_user('newbie', days_old=1)
        post = self.post()
        self.login(newbie)
        with override_settings(NEW_ACCOUNT_COMMENTS_PER_DAY=2):
            for n in range(4):
                self.client.post(reverse('add_comment', args=[post.pk]), {'body': f'c{n}'})
        self.assertEqual(Comment.objects.filter(user=newbie).count(), 2)

    def test_mentions_notify_case_insensitively_and_ignore_unknown(self):
        post = self.post()
        self.login(self.bob)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'hey @ALICE and @nobody, thoughts?'})
        self.assertEqual(Notification.objects.filter(recipient=self.alice, notification_type='mention').count(), 1)


class VoteAndKarmaTests(BaseCase):
    def test_post_votes_build_karma_and_toggle_off(self):
        post = self.post()
        self.login(self.bob)
        self.client.post(reverse('toggle_post_vote', args=[post.pk]))
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.karma_score, 1)
        self.client.post(reverse('toggle_post_vote', args=[post.pk]))
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.karma_score, 0)

    def test_comment_votes_count_towards_karma_but_not_self_votes(self):
        post = self.post()
        comment = Comment.objects.create(post=post, user=self.bob, body='useful')
        self.login(self.alice)
        self.client.post(reverse('toggle_comment_vote', args=[comment.pk]))
        comment.refresh_from_db()
        self.bob.refresh_from_db()
        self.assertEqual((comment.upvotes, self.bob.karma_score), (1, 1))
        self.login(self.bob)
        self.client.post(reverse('toggle_comment_vote', args=[comment.pk]))
        self.assertEqual(CommentVote.objects.filter(user=self.bob).count(), 0)

    def test_karma_recalculation_ignores_self_votes_already_in_the_database(self):
        post = self.post()
        post.votes.create(user=self.alice)
        post.votes.create(user=self.bob)
        self.assertEqual(recalculate_karma(self.alice), 1)

    def test_htmx_vote_returns_partial_not_a_full_page(self):
        post = self.post()
        self.login(self.bob)
        response = self.client.post(reverse('toggle_post_vote', args=[post.pk]), HTTP_HX_REQUEST='true')
        self.assertContains(response, 'id="post-vote"')
        self.assertNotContains(response, '<html')
        self.assertContains(response, 'Upvoted')


class PostDetailPageTests(BaseCase):
    def test_anonymous_visitor_sees_a_log_in_to_upvote_link_not_a_dead_button(self):
        post = self.post()
        response = self.client.get(post.get_absolute_url())
        self.assertContains(response, 'Log in to upvote')
        self.assertContains(response, f'{reverse("login")}?next={post.get_absolute_url()}')

    def test_post_author_sees_a_non_interactive_vote_count_not_a_login_link(self):
        post = self.post()
        self.login(self.alice)
        response = self.client.get(post.get_absolute_url())
        self.assertNotContains(response, 'Log in to upvote')
        self.assertContains(response, 'cannot upvote your own post')

    def test_other_logged_in_users_still_get_the_real_vote_button(self):
        post = self.post()
        self.login(self.bob)
        response = self.client.get(post.get_absolute_url())
        self.assertNotContains(response, 'Log in to upvote')
        self.assertContains(response, 'id="post-vote"')

    def test_breadcrumb_shows_home_category_and_post_title(self):
        post = self.post()
        response = self.client.get(post.get_absolute_url())
        self.assertContains(response, 'class="breadcrumb"')
        self.assertContains(response, self.category.get_absolute_url())
        self.assertContains(response, post.title)

    def test_share_menu_offers_copy_link_whatsapp_and_facebook(self):
        post = self.post()
        response = self.client.get(post.get_absolute_url())
        absolute_url = response.context['canonical_url']
        self.assertContains(response, 'share-copy')
        self.assertContains(response, f'data-share-url="{absolute_url}"')
        self.assertContains(response, 'wa.me')
        self.assertContains(response, 'facebook.com/sharer')


class ReportTests(BaseCase):
    def test_report_post_and_comment_once_each(self):
        post = self.post()
        comment = Comment.objects.create(post=post, user=self.alice, body='spammy')
        self.login(self.bob)
        self.assertEqual(self.client.get(reverse('report_post', args=[post.pk])).status_code, 200)
        self.client.post(reverse('report_post', args=[post.pk]), {'category': 'spam'})
        self.client.post(reverse('report_post', args=[post.pk]), {'category': 'spam'})
        self.client.post(reverse('report_comment', args=[comment.pk]), {'category': 'hype'})
        self.assertEqual(Report.objects.filter(post=post).count(), 1)
        self.assertEqual(Report.objects.filter(comment=comment).count(), 1)
        self.assertEqual(Report.objects.get(post=post).reason, 'Spam or scam')

    def test_cannot_report_own_content_and_other_needs_details(self):
        post = self.post()
        self.login(self.alice)
        self.client.post(reverse('report_post', args=[post.pk]), {'category': 'spam'})
        self.assertEqual(Report.objects.count(), 0)
        self.login(self.bob)
        response = self.client.post(reverse('report_post', args=[post.pk]), {'category': 'other', 'reason': ''})
        self.assertContains(response, 'describe the problem')

    def test_reporting_requires_login(self):
        post = self.post()
        response = self.client.post(reverse('report_post', args=[post.pk]), {'category': 'spam'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)


class ContactTests(BaseCase):
    def payload(self, **overrides):
        data = {'name': 'Carol', 'email': 'carol@example.com', 'subject': 'Question', 'message': 'How do verified badges work?'}
        data.update(overrides)
        return data

    def test_anonymous_visitor_can_send_a_message(self):
        response = self.client.post(reverse('contact'), self.payload())
        self.assertEqual(response.status_code, 302)
        message = ContactMessage.objects.get()
        self.assertEqual(message.email, 'carol@example.com')
        self.assertIsNone(message.user)
        self.assertFalse(message.is_resolved)

    def test_logged_in_users_message_is_linked_to_their_account(self):
        self.login(self.alice)
        self.client.post(reverse('contact'), self.payload())
        self.assertEqual(ContactMessage.objects.get().user, self.alice)

    def test_logged_in_users_form_is_prefilled(self):
        self.login(self.alice)
        response = self.client.get(reverse('contact'))
        self.assertContains(response, 'alice@example.com')

    def test_blank_message_is_rejected(self):
        response = self.client.post(reverse('contact'), self.payload(message=''))
        self.assertEqual(ContactMessage.objects.count(), 0)
        self.assertContains(response, 'field-errors')

    def test_contact_form_is_rate_limited_per_address(self):
        with override_settings(CONTACT_MAX_PER_HOUR=2):
            for n in range(3):
                response = self.client.post(reverse('contact'), self.payload(subject=f'Question {n}'))
            self.assertEqual(response.status_code, 429)
            self.assertEqual(ContactMessage.objects.count(), 2)

    def test_contact_honeypot_field_blocks_submission(self):
        response = self.client.post(reverse('contact'), self.payload(website='http://spam.example'))
        self.assertContains(response, 'Please try again')
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_contact_submitted_too_fast_is_blocked(self):
        response = self.client.post(reverse('contact'), self.payload(form_rendered_at=time.time()))
        self.assertContains(response, 'Please try again')
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_contact_succeeds_with_empty_honeypot_and_a_plausible_delay(self):
        response = self.client.post(reverse('contact'), self.payload(website='', form_rendered_at=time.time() - 10))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_contact_message_over_5000_characters_is_rejected(self):
        response = self.client.post(reverse('contact'), self.payload(message='x' * 5001))
        self.assertEqual(ContactMessage.objects.count(), 0)
        self.assertContains(response, 'field-errors')

    def test_contact_message_at_exactly_5000_characters_is_accepted(self):
        response = self.client.post(reverse('contact'), self.payload(message='x' * 5000))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactMessage.objects.count(), 1)

    @override_settings(TURNSTILE_SECRET_KEY='test-secret-key')
    def test_contact_blocked_without_a_turnstile_token_when_configured(self):
        response = self.client.post(reverse('contact'), self.payload())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ContactMessage.objects.count(), 0)


class ModerationTests(BaseCase):
    def report(self, target, by, category='spam'):
        kwargs = {'comment': target} if isinstance(target, Comment) else {'post': target}
        return Report.objects.create(reporter=by, category=category, reason='r', **kwargs)

    def test_dashboard_is_staff_only(self):
        self.assertEqual(self.client.get(reverse('moderation_dashboard')).status_code, 302)
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse('moderation_dashboard')).status_code, 403)
        self.assertEqual(self.client.post(reverse('moderation_action'), {'target_type': 'post', 'target_id': 1, 'action': 'remove'}).status_code, 403)
        self.login(self.staff)
        self.assertEqual(self.client.get(reverse('moderation_dashboard')).status_code, 200)

    def test_queue_sorted_by_report_count(self):
        quiet, loud = self.post(title='Quiet'), self.post(title='Loud')
        self.report(quiet, self.bob)
        for reporter in (self.bob, self.staff, make_user('carol')):
            self.report(loud, reporter)
        self.login(self.staff)
        groups = self.client.get(reverse('moderation_dashboard')).context['groups']
        self.assertEqual([(g['target'].title, g['count']) for g in groups], [('Loud', 3), ('Quiet', 1)])

    def act(self, kind, target, action, **extra):
        return self.client.post(reverse('moderation_action'), {'target_type': kind, 'target_id': target.pk, 'action': action, **extra})

    def test_remove_hides_post_notifies_author_and_resolves_reports(self):
        post = self.post()
        self.report(post, self.bob)
        self.login(self.staff)
        self.act('post', post, 'remove')
        post.refresh_from_db()
        self.assertTrue(post.is_removed)
        self.assertEqual(Report.objects.get().status, Report.STATUS_ACTIONED)
        self.assertTrue(Notification.objects.filter(recipient=self.alice, notification_type='moderation').exists())
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)  # staff can still see it
        self.client.logout()
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get('/'), post.title)
        self.login(self.staff)
        self.act('post', post, 'restore')
        post.refresh_from_db()
        self.assertFalse(post.is_removed)

    def test_dismiss_lock_and_unlock(self):
        post = self.post()
        self.report(post, self.bob)
        self.login(self.staff)
        self.act('post', post, 'dismiss')
        self.assertEqual(Report.objects.get().status, Report.STATUS_DISMISSED)
        self.act('post', post, 'lock')
        post.refresh_from_db()
        self.assertTrue(post.is_locked)
        self.act('post', post, 'unlock')
        post.refresh_from_db()
        self.assertFalse(post.is_locked)

    def test_removed_comment_shows_placeholder_and_lock_via_comment_target(self):
        post = self.post()
        comment = Comment.objects.create(post=post, user=self.bob, body='rule-breaking words')
        self.login(self.staff)
        self.act('comment', comment, 'remove')
        self.assertNotContains(self.client.get(post.get_absolute_url()), 'rule-breaking words')
        self.act('comment', comment, 'lock')
        post.refresh_from_db()
        self.assertTrue(post.is_locked)

    def test_shadow_ban_hides_content_from_others_but_not_author_or_staff(self):
        post = self.post(title='Ghost post')
        comment = Comment.objects.create(post=post, user=self.alice, body='ghost comment')
        other_post = self.post(user=self.bob, title='Visible post')
        Comment.objects.create(post=other_post, user=self.alice, body='ghost reply')
        self.login(self.staff)
        self.act('post', post, 'shadowban')
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_shadow_banned)
        self.assertFalse(Notification.objects.filter(recipient=self.alice).exists())  # ban is silent

        self.login(self.bob)
        self.assertNotContains(self.client.get('/'), 'Ghost post')
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(other_post.get_absolute_url()), 'ghost reply')
        self.assertNotContains(self.client.get(reverse('search'), {'q': 'Ghost'}), 'Ghost post')
        self.assertNotContains(self.client.get(reverse('profile', args=['alice'])), 'Ghost post')
        self.assertNotContains(self.client.get(reverse('sitemap')), post.get_absolute_url())

        self.login(self.alice)  # the author still sees their own content
        self.assertContains(self.client.get('/'), 'Ghost post')
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)
        self.assertContains(self.client.get(other_post.get_absolute_url()), 'ghost reply')

        self.login(self.staff)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)
        self.act('post', post, 'unshadowban')
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_shadow_banned)

    def test_shadow_banned_actions_do_not_notify_others(self):
        self.alice.is_shadow_banned = True
        self.alice.save()
        post = self.post(user=self.bob)
        self.login(self.alice)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'hi'})
        self.client.post(reverse('toggle_follow', args=['bob']))
        self.assertFalse(Notification.objects.filter(recipient=self.bob).exists())

    def test_staff_cannot_be_shadow_banned(self):
        post = self.post(user=self.staff)
        self.login(self.staff)
        self.act('post', post, 'shadowban')
        self.staff.refresh_from_db()
        self.assertFalse(self.staff.is_shadow_banned)

    def test_unknown_target_or_action_is_handled(self):
        self.login(self.staff)
        self.assertEqual(self.client.post(reverse('moderation_action'), {'target_type': 'user', 'target_id': 1, 'action': 'remove'}).status_code, 302)
        post = self.post()
        self.act('post', post, 'explode')
        post.refresh_from_db()
        self.assertFalse(post.is_removed)

    def test_pump_watch_flags_bursts_from_several_authors(self):
        carol, dave = make_user('carol'), make_user('dave')
        for user in (self.alice, self.bob, carol, dave, self.alice):
            self.post(user=user, asset=self.asset, title=f'Hype {user.username}')
        self.assertEqual([t.ticker for t in pump_watch()], ['NABIL'])
        self.login(self.staff)
        self.assertContains(self.client.get(reverse('moderation_dashboard')), 'NABIL')

    def test_pump_watch_ignores_one_author_and_old_posts(self):
        for n in range(6):
            self.post(user=self.alice, asset=self.asset, title=f'Solo {n}')
        self.assertEqual(list(pump_watch()), [])
        Post.objects.update(created_at=timezone.now() - timedelta(days=3))
        for user in (self.alice, self.bob, self.staff):
            Post.objects.filter(user=user).update(created_at=timezone.now() - timedelta(days=3))
        self.assertEqual(list(pump_watch()), [])


class VerificationTests(BaseCase):
    def application(self, user, **extra):
        return VerificationRequest.objects.create(user=user, full_name='N', requested_type='Verified Fund Manager', **extra)

    def test_approval_grants_requested_badge_type_once(self):
        app = self.application(self.alice)
        self.login(self.staff)
        self.client.post(reverse('review_verification', args=[app.pk]), {'action': 'approve'})
        self.alice.refresh_from_db()
        self.assertEqual((self.alice.is_verified, self.alice.verified_type), (True, 'Verified Fund Manager'))
        self.assertContains(self.client.get(self.post().get_absolute_url()), 'Verified Fund Manager')
        # A second review of the same application is refused.
        self.client.post(reverse('review_verification', args=[app.pk]), {'action': 'reject', 'rejection_reason': 'late'})
        app.refresh_from_db()
        self.assertEqual(app.status, 'approved')

    def test_rejecting_a_new_application_keeps_an_existing_badge(self):
        self.alice.is_verified, self.alice.verified_type = True, 'Verified Analyst'
        self.alice.save()
        app = self.application(self.alice)
        self.login(self.staff)
        self.client.post(reverse('review_verification', args=[app.pk]), {'action': 'reject', 'rejection_reason': 'No'})
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.is_verified)

    def test_verified_members_cannot_reapply_and_dashboard_is_staff_only(self):
        self.alice.is_verified = True
        self.alice.save()
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse('verification_apply')).status_code, 302)
        self.assertEqual(self.client.get(reverse('verification_dashboard')).status_code, 403)

    def test_disclaimer_on_apply_page_frames_verification_as_identity_only(self):
        self.login(self.alice)
        self.assertContains(self.client.get(reverse('verification_apply')), 'does not mean MarketKuraa endorses')


class AmaTests(BaseCase):
    def ama(self, **kwargs):
        defaults = {'type': 'ama', 'title': 'Ask me about REITs', 'body': 'AMA intro', 'user': self.alice,
                    'ama_starts_at': timezone.now() - timedelta(hours=1), 'ama_ends_at': timezone.now() + timedelta(hours=1)}
        defaults.update(kwargs)
        return self.post(**defaults)

    def data(self, **overrides):
        base = {'category': self.category.pk, 'type': 'ama', 'title': 'AMA', 'body': 'Ask away',
                'ama_starts_at': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
                'ama_ends_at': (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')}
        base.update(overrides)
        return base

    def test_only_verified_members_can_host(self):
        self.login(self.bob)
        self.assertNotContains(self.client.get(reverse('create_post')), 'value="ama"')
        self.client.post(reverse('create_post'), self.data())
        self.assertFalse(Post.objects.filter(type='ama').exists())
        self.bob.is_verified = True
        self.bob.save()
        self.assertContains(self.client.get(reverse('create_post')), 'value="ama"')
        self.assertEqual(self.client.post(reverse('create_post'), self.data()).status_code, 302)
        self.assertEqual(Post.objects.get(type='ama').user, self.bob)

    def test_ama_end_must_follow_start(self):
        self.bob.is_verified = True
        self.bob.save()
        self.login(self.bob)
        response = self.client.post(reverse('create_post'), self.data(ama_ends_at='2020-01-01T00:00'))
        self.assertContains(response, 'must end after it starts')

    def test_questions_and_host_answers_are_structured(self):
        post = self.ama()
        question = Comment.objects.create(post=post, user=self.bob, body='Are REITs worth it?')
        Comment.objects.create(post=post, user=self.staff, body='second question')
        page = self.client.get(post.get_absolute_url())
        self.assertContains(page, 'Live now')
        self.assertContains(page, '2 unanswered')
        Comment.objects.create(post=post, user=self.alice, body='Yes, mostly.', parent_comment=question)
        page = self.client.get(post.get_absolute_url())
        self.assertContains(page, '1 unanswered')
        self.assertContains(page, 'host-answer')
        self.assertIn('"QAPage"', page.content.decode())
        self.assertIn('acceptedAnswer', page.content.decode())

    def test_ended_ama_only_accepts_the_host(self):
        post = self.ama(ama_ends_at=timezone.now() - timedelta(minutes=1))
        question = Comment.objects.create(post=post, user=self.bob, body='late question')
        self.login(self.bob)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'too late'})
        self.assertEqual(Comment.objects.filter(post=post).count(), 1)
        self.login(self.alice)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'host answers late', 'parent_comment': question.pk})
        self.assertEqual(Comment.objects.filter(post=post).count(), 2)
        self.assertContains(self.client.get(post.get_absolute_url()), 'Ended')


class StartupTests(BaseCase):
    def data(self, **overrides):
        base = {'name': 'Himal Robotics', 'tagline': 'Robots for terrace farms', 'description': 'We build things.', 'sector': 'AgriTech',
                'stage': 'seed', 'location': 'Kathmandu', 'website_url': '', 'looking_for': 'Advisors'}
        base.update(overrides)
        return base

    def test_profile_creation_is_reputation_gated(self):
        self.login(self.alice)
        response = self.client.get(reverse('startup_create'))
        self.assertRedirects(response, reverse('startups'), fetch_redirect_response=False)
        self.assertEqual(StartupProfile.objects.count(), 0)
        self.alice.karma_score = 10
        self.alice.save()
        self.assertEqual(self.client.get(reverse('startup_create')).status_code, 200)

    def test_verified_members_bypass_karma_gate(self):
        self.alice.is_verified = True
        self.alice.save()
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse('startup_create')).status_code, 200)

    def test_profile_hidden_until_approved_then_listed(self):
        self.alice.karma_score = 10
        self.alice.save()
        self.login(self.alice)
        self.client.post(reverse('startup_create'), self.data())
        startup = StartupProfile.objects.get()
        self.assertFalse(startup.is_approved)
        self.assertEqual(startup.slug, 'himal-robotics')
        self.assertContains(self.client.get(startup.get_absolute_url()), 'Awaiting moderator approval')
        self.login(self.bob)
        self.assertEqual(self.client.get(startup.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse('startups')), 'Himal Robotics')
        self.login(self.staff)
        self.assertContains(self.client.get(reverse('moderation_dashboard')), 'Himal Robotics')
        self.client.post(reverse('approve_startup', args=[startup.pk]))
        self.assertTrue(StartupProfile.objects.get().is_approved)
        self.login(self.bob)
        self.assertContains(self.client.get(reverse('startups')), 'Himal Robotics')
        self.assertContains(self.client.get(reverse('startups'), {'stage': 'seed', 'sector': 'agritech'}), 'Himal Robotics')
        self.assertNotContains(self.client.get(reverse('startups'), {'stage': 'idea'}), 'Himal Robotics')

    def test_editing_requeues_for_approval_and_only_owner_can_edit(self):
        startup = StartupProfile.objects.create(owner=self.alice, name='Edit Me', tagline='t', description='d', is_approved=True)
        self.login(self.bob)
        self.assertEqual(self.client.get(reverse('startup_edit', args=[startup.slug])).status_code, 404)
        self.login(self.alice)
        self.client.post(reverse('startup_edit', args=[startup.slug]), self.data(name='Edit Me', tagline='new tagline'))
        startup.refresh_from_db()
        self.assertEqual(startup.tagline, 'new tagline')
        self.assertFalse(startup.is_approved)

    def test_slug_collisions_get_suffixes(self):
        first = StartupProfile.objects.create(owner=self.alice, name='Same', tagline='t', description='d')
        second = StartupProfile.objects.create(owner=self.bob, name='Same', tagline='t', description='d')
        self.assertEqual((first.slug, second.slug), ('same', 'same-2'))

    def test_startups_limited_to_three_per_member(self):
        self.alice.is_verified = True
        self.alice.save()
        for n in range(3):
            StartupProfile.objects.create(owner=self.alice, name=f'S{n}', tagline='t', description='d')
        self.login(self.alice)
        self.assertRedirects(self.client.get(reverse('startup_create')), reverse('startups'), fetch_redirect_response=False)


class FeedTests(BaseCase):
    def test_following_tab_shows_followed_users_and_categories(self):
        followed_post = self.post(user=self.bob, title='From bob')
        other_cat = Category.objects.get(slug='market-news')
        cat_post = self.post(user=self.staff, category=other_cat, title='In market news')
        stranger = self.post(user=self.staff, title='Unrelated')
        self.login(self.alice)
        self.assertNotContains(self.client.get('/', {'tab': 'following'}), 'From bob')
        self.client.post(reverse('toggle_follow', args=['bob']))
        self.client.post(reverse('toggle_category_follow', args=['market-news']))
        page = self.client.get('/', {'tab': 'following'})
        self.assertContains(page, 'From bob')
        self.assertContains(page, 'In market news')
        self.assertNotContains(page, 'Unrelated')
        self.assertEqual(CategoryFollow.objects.count(), 1)
        self.client.post(reverse('toggle_category_follow', args=['market-news']))
        self.assertEqual(CategoryFollow.objects.count(), 0)
        del followed_post, cat_post, stranger

    def test_trending_ranks_by_votes_and_comments(self):
        quiet = self.post(title='Quiet thread')
        busy = self.post(title='Busy thread')
        for n in range(3):
            Comment.objects.create(post=busy, user=self.bob, body=f'c{n}')
        page = self.client.get('/', {'tab': 'trending'})
        titles = [p.title for p in page.context['posts']]
        self.assertEqual(titles, ['Busy thread', 'Quiet thread'])
        del quiet

    def test_profile_tabs_show_comment_history(self):
        post = self.post(user=self.bob, title='Bob post')
        Comment.objects.create(post=post, user=self.alice, body='alice wrote this')
        self.assertContains(self.client.get(reverse('profile', args=['alice']), {'tab': 'comments'}), 'alice wrote this')

    def test_category_page_filters_and_lists(self):
        self.post(title='Category thread')
        self.assertContains(self.client.get(self.category.get_absolute_url()), 'Category thread')
        self.assertNotContains(self.client.get(self.category.get_absolute_url(), {'q': 'zzz'}), 'Category thread')


class LocalisationTests(BaseCase):
    def test_language_can_be_switched_to_nepali(self):
        response = self.client.post(reverse('set_language'), {'language': 'ne', 'next': '/'}, follow=True)
        self.assertContains(response, 'लग इन')
        self.assertContains(response, 'lang="ne"')

    def test_english_is_the_default(self):
        response = self.client.get('/')
        self.assertContains(response, 'lang="en"')
        self.assertContains(response, 'Log in')

    def test_local_naturaltime_in_english(self):
        from django.utils import translation
        from community.templatetags.community_extras import local_naturaltime
        with translation.override('en'):
            self.assertEqual(local_naturaltime(timezone.now() - timedelta(seconds=10)), 'just now')
            self.assertEqual(local_naturaltime(timezone.now() - timedelta(days=52)), '1 month, 3 weeks ago')
            self.assertEqual(local_naturaltime(timezone.now() - timedelta(hours=3)), '3 hours ago')
            self.assertEqual(local_naturaltime(timezone.now() - timedelta(hours=1)), '1 hour ago')

    def test_local_naturaltime_in_nepali_has_correct_spacing_and_units(self):
        from django.utils import translation
        from community.templatetags.community_extras import local_naturaltime
        with translation.override('ne'):
            self.assertEqual(local_naturaltime(timezone.now() - timedelta(seconds=10)), 'भर्खरै')
            result = local_naturaltime(timezone.now() - timedelta(days=52))
            self.assertEqual(result, '1 महिना 3 हप्ता अघि')
            # The original bug: no space between the two units, and English unit words.
            self.assertNotIn('महिना3', result)
            self.assertNotIn('month', result)
            self.assertNotIn('week', result)

    def test_category_display_name_is_translated_in_nepali_and_english_elsewhere(self):
        from django.utils import translation
        with translation.override('en'):
            self.assertEqual(self.category.display_name, 'NEPSE')
        with translation.override('ne'):
            self.assertEqual(self.category.display_name, 'नेप्से')

    def test_category_display_name_falls_back_for_an_unmapped_category(self):
        from django.utils import translation
        custom = Category.objects.create(name='Commodities', slug='commodities')
        with translation.override('ne'):
            self.assertEqual(custom.display_name, 'Commodities')

    def test_feed_card_shows_localised_relative_time_in_nepali(self):
        self.post()
        self.client.post(reverse('set_language'), {'language': 'ne', 'next': '/'})
        response = self.client.get('/')
        self.assertContains(response, 'भर्खरै')

    def test_markdown_toolbar_labels_are_translated_in_nepali(self):
        self.login(self.alice)
        self.client.post(reverse('set_language'), {'language': 'ne', 'next': reverse('create_post')})
        response = self.client.get(reverse('create_post'))
        # json_script emits ASCII-safe \uXXXX escapes (ensure_ascii=True), not raw UTF-8 bytes —
        # JS's JSON.parse decodes these correctly at runtime, so this is the right thing for the
        # test to look for too, not the literal Devanagari substring.
        self.assertContains(response, '\\u092c\\u094b\\u0932\\u094d\\u0921')
        self.assertNotContains(response, '"bold": "Bold"')


class SearchTests(BaseCase):
    def titles(self, query, **params):
        response = self.client.get(reverse('search'), {'q': query, **params})
        return [p.title for p in response.context['posts']]

    def test_search_finds_posts_companies_tags_and_users(self):
        self.post(title='Nabil earnings', body='Quarterly numbers', asset=self.asset)
        tagged = self.post(title='Sector view', body='banks')
        PostTag.objects.create(post=tagged, tag=Tag.objects.create(name='banking', slug='banking', is_company=False))
        response = self.client.get(reverse('search'), {'q': 'nabil'})
        self.assertEqual([p.title for p in response.context['posts']], ['Nabil earnings'])
        self.assertContains(response, 'Nabil Bank Limited')
        self.assertContains(self.client.get(reverse('search'), {'q': 'banking'}), '/company/banking/')
        self.assertContains(self.client.get(reverse('search'), {'q': 'alic'}), '/u/alice/')

    def test_search_matches_nepali_text(self):
        self.post(title='नेप्से बजार विश्लेषण', body='आजको बजार')
        self.post(title='Unrelated', body='something else')
        self.assertEqual(self.titles('बजार'), ['नेप्से बजार विश्लेषण'])

    def test_search_matches_ticker_fragment(self):
        self.post(title='Untitled', body='no mention', asset=self.asset)
        self.assertEqual(self.titles('NAB'), ['Untitled'])

    def test_search_finds_posts_only_in_a_matching_category(self):
        # self.category is slug='nepse', name='NEPSE' — none of these posts mention "NEPSE" in
        # their own title or body, only via their category. This was the reported bug: 3 of 4
        # NEPSE posts (everything but the one with "NEPSE" literally in its title) went missing.
        self.post(title='What going on market', body='Today market details')
        self.post(title='New market system', body='Whats going on today')
        self.post(title='Welcome to MarketKuraa', body='Live and ready.')
        other_category = Category.objects.create(name='Personal Finance', slug='personal-finance-test')
        self.post(title='Budgeting basics', body='unrelated', category=other_category)
        self.assertEqual(
            set(self.titles('NEPSE')),
            {'What going on market', 'New market system', 'Welcome to MarketKuraa'},
        )

    def test_search_results_include_a_matching_category(self):
        response = self.client.get(reverse('search'), {'q': 'NEPSE'})
        self.assertContains(response, self.category.get_absolute_url())
        self.assertContains(response, 'NEPSE')

    def test_search_finds_posts_by_topic_tag(self):
        tagged = self.post(title='Sector view', body='no keyword here')
        PostTag.objects.create(post=tagged, tag=Tag.objects.create(name='ipo', slug='ipo-search-test', is_company=False))
        self.assertEqual(self.titles('ipo'), ['Sector view'])

    def test_search_ranks_title_matches_above_body_matches_regardless_of_database(self):
        # The Postgres-only ranking test above (test_postgres_full_text_ranks_title_matches_first)
        # only runs against Postgres. This covers the same requirement end to end on whatever
        # database the suite is actually running against (SQLite in dev).
        body_only = self.post(title='Weekly thread', body='People keep asking about dividends here.')
        title_match = self.post(title='Dividends explained', body='A primer.')
        Post.objects.filter(pk=title_match.pk).update(created_at=timezone.now() - timedelta(days=5))
        self.assertEqual(self.titles('dividends'), ['Dividends explained', 'Weekly thread'])
        del body_only

    def test_search_is_case_insensitive(self):
        self.post(title='NEPSE outlook', body='case test')
        self.assertEqual(self.titles('nepse'), ['NEPSE outlook'])
        self.assertEqual(self.titles('NEPSE'), ['NEPSE outlook'])
        self.assertEqual(self.titles('NePsE'), ['NEPSE outlook'])

    @skipUnless(connection.vendor == 'postgresql', 'Full-text ranking needs PostgreSQL')
    def test_postgres_full_text_ranks_title_matches_first(self):
        body_only = self.post(title='Weekly thread', body='People keep asking about dividends here.')
        title_match = self.post(title='Dividends explained', body='A primer.')
        Post.objects.filter(pk=title_match.pk).update(created_at=timezone.now() - timedelta(days=5))  # older, must still rank first
        self.assertEqual(self.titles('dividends'), ['Dividends explained', 'Weekly thread'])
        del body_only

    @skipUnless(connection.vendor == 'postgresql', 'Full-text ranking needs PostgreSQL')
    def test_postgres_websearch_syntax(self):
        self.post(title='Banks and hydro', body='mixed')
        self.post(title='Banks only', body='pure')
        self.assertEqual(self.titles('banks -hydro'), ['Banks only'])
        self.assertEqual(sorted(self.titles('"banks and hydro"')), ['Banks and hydro'])


class HomePageTests(BaseCase):
    def home(self, **params):
        return self.client.get(reverse('home'), params)

    def test_anonymous_sees_join_prompt_and_no_composer(self):
        self.post()
        page = self.home()
        self.assertContains(page, 'Join the discussion')
        self.assertNotContains(page, 'id="c-title"')
        self.assertContains(page, 'aria-label="Log in to upvote"')  # anonymous vote arrows lead to login

    def test_member_sees_working_composer(self):
        self.login(self.alice)
        page = self.home()
        self.assertContains(page, 'id="c-title"')
        self.assertContains(page, 'Write a thesis')
        response = self.client.post(reverse('create_post'), {'type': 'discussion', 'category': self.category.pk, 'title': 'Composer post',
                                                            'body': 'Written on the home page', 'asset_tag': 'nabil'})
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title='Composer post')
        self.assertEqual(post.asset, self.asset)  # ticker typed in any case resolves to the company
        self.assertContains(self.home(), 'Composer post')

    def test_thesis_link_preselects_thesis_type(self):
        self.login(self.alice)
        page = self.client.get(reverse('create_post'), {'type': 'thesis'})
        self.assertContains(page, '<option value="thesis" selected>')

    def test_category_chips_filter_and_keep_the_tab(self):
        other = Category.objects.get(slug='market-news')
        self.post(title='In nepse')
        self.post(title='In news', category=other)
        page = self.home(category='market-news')
        self.assertEqual([p.title for p in page.context['posts']], ['In news'])
        self.assertContains(page, 'chip-filter active')
        self.assertEqual([p.title for p in self.home(category='market-news', tab='trending').context['posts']], ['In news'])

    def test_tab_and_chip_links_are_query_strings_not_bare_paths(self):
        # Regression: these must start with "?" — without it, the browser treats the query
        # string as a relative path segment (e.g. "category=x" resolves to "/category=x", 404).
        page = self.home().content.decode()
        self.assertIn('href="?tab=trending', page)
        self.assertIn('href="?category=market-news', page)
        self.assertNotIn('href="tab=', page)
        self.assertNotIn('href="category=', page)

    def test_rail_navigation_type_filters(self):
        self.post(title='A discussion')
        self.post(title='A thesis', type='thesis', position_type='long', entry_price=10, time_horizon='long')
        self.assertEqual([p.title for p in self.home(type='thesis').context['posts']], ['A thesis'])
        self.assertContains(self.home(type='thesis'), 'aria-current="page"')

    def test_cards_show_replies_read_time_ticker_and_thesis_details(self):
        post = self.post(title='Card details', asset=self.asset, type='thesis', position_type='short', entry_price='120.50', target_price='90', time_horizon='medium')
        Comment.objects.create(post=post, user=self.bob, body='c')
        page = self.home()
        self.assertContains(page, '$NABIL')
        self.assertContains(page, '1 reply')
        self.assertContains(page, '1 min read')
        self.assertContains(page, 'pos-short')
        self.assertContains(page, 'Entry 120.5')

    def test_thesis_card_with_no_reported_fields_has_no_empty_metadata_bar(self):
        # position_type/entry_price/target_price/time_horizon are all blank=True — a thesis post
        # can legitimately have none of them set. The card used to render `.thesis-line` anyway,
        # as a styled bar with no text in it at all.
        self.post(title='Bare thesis', type='thesis', position_type='', entry_price=None, target_price=None, time_horizon='')
        page = self.home()
        self.assertContains(page, 'Bare thesis')
        self.assertNotContains(page, 'thesis-line')

    def test_thesis_detail_page_with_no_reported_fields_has_no_empty_summary_line(self):
        post = self.post(title='Bare thesis detail', type='thesis', position_type='', entry_price=None, target_price=None, time_horizon='', thesis_risk='Could go either way')
        page = self.client.get(post.get_absolute_url())
        self.assertContains(page, 'Could go either way')
        self.assertNotContains(page, '<strong>Position:</strong>')
        self.assertNotContains(page, '<strong>Entry:</strong>')

    def test_card_vote_shows_state_and_htmx_swaps_only_the_card_fragment(self):
        post = self.post(user=self.bob)
        self.login(self.alice)
        self.assertContains(self.home(), 'aria-pressed="false"')
        response = self.client.post(reverse('toggle_post_vote', args=[post.pk]), HTTP_HX_REQUEST='true', HTTP_HX_TARGET=f'card-vote-{post.pk}')
        self.assertContains(response, f'id="card-vote-{post.pk}"')
        self.assertContains(response, 'aria-pressed="true"')
        self.assertNotContains(response, '<html')
        self.assertContains(self.home(), 'aria-pressed="true"')  # persisted, and shown on the list after reload
        # The post page keeps its own fragment.
        response = self.client.post(reverse('toggle_post_vote', args=[post.pk]), HTTP_HX_REQUEST='true', HTTP_HX_TARGET='post-vote')
        self.assertContains(response, 'id="post-vote"')

    def test_own_post_cannot_be_upvoted_from_the_card(self):
        self.post(user=self.alice)
        self.login(self.alice)
        self.assertNotContains(self.home(), 'hx-post="/post/')

    def test_most_discussed_strip_counts_recent_posts_only_and_hides_banned_authors(self):
        for n in range(2):
            self.post(asset=self.asset, title=f'Recent {n}')
        old = Tag.objects.create(name='OLDCO', slug='oldco', ticker='OLDCO')
        Post.objects.filter(pk=self.post(asset=old, title='Old').pk).update(created_at=timezone.now() - timedelta(days=30))
        ghost_asset = Tag.objects.create(name='GHOST', slug='ghost', ticker='GHOST')
        self.post(user=make_user('ghost', is_shadow_banned=True), asset=ghost_asset, title='Hidden')
        names = [c.ticker for c in self.home().context['trending_companies']]
        self.assertEqual(names, ['NABIL'])
        self.assertContains(self.home(), 'Live prices · coming soon')

    def test_thesis_split_needs_enough_theses_and_computes_percentages(self):
        def thesis(position):
            return self.post(asset=self.asset, type='thesis', position_type=position, entry_price=1, time_horizon='long', title=f't-{position}')
        thesis('long'), thesis('long')
        self.assertEqual(self.home().context['thesis_sentiment'], [])  # only 2 theses: not enough to mean anything
        thesis('short')
        row = self.home().context['thesis_sentiment'][0]
        self.assertEqual((row.theses, row.long_pct, row.short_pct), (3, 67, 33))
        self.assertContains(self.home(), '67% long')
        self.assertContains(self.home(), 'not a signal or recommendation')

    def test_thesis_split_ignores_watching_removed_and_banned(self):
        for position in ('long', 'long', 'long'):
            self.post(asset=self.asset, type='thesis', position_type=position, entry_price=1, time_horizon='long')
        self.post(asset=self.asset, type='thesis', position_type='watching', entry_price=1, time_horizon='long')
        self.post(asset=self.asset, type='thesis', position_type='short', entry_price=1, time_horizon='long', is_removed=True)
        row = self.home().context['thesis_sentiment'][0]
        self.assertEqual((row.theses, row.long_pct), (3, 100))

    def test_amas_widget_lists_live_and_upcoming_but_not_ended(self):
        now = timezone.now()
        self.post(type='ama', title='Live AMA', ama_starts_at=now - timedelta(hours=1), ama_ends_at=now + timedelta(hours=1))
        self.post(type='ama', title='Future AMA', ama_starts_at=now + timedelta(days=2), ama_ends_at=now + timedelta(days=2, hours=1))
        self.post(type='ama', title='Past AMA', ama_starts_at=now - timedelta(days=3), ama_ends_at=now - timedelta(days=2))
        titles = [a.title for a in self.home().context['upcoming_amas']]
        self.assertEqual(titles, ['Live AMA', 'Future AMA'])

    def test_top_contributors_ranked_by_karma_and_exclude_banned_and_zero(self):
        make_user('zero')
        make_user('star', karma_score=50)
        make_user('shadow', karma_score=999, is_shadow_banned=True)
        self.bob.karma_score = 7
        self.bob.save()
        names = [u.username for u in self.home().context['top_contributors']]
        self.assertEqual(names, ['star', 'bob'])
        self.assertContains(self.home(), 'not by returns')

    def test_market_hours_markup_lists_exchanges_with_time_zones(self):
        page = self.home()
        for tz in ('Asia/Kathmandu', 'Asia/Kolkata', 'Europe/London', 'America/New_York', 'Asia/Tokyo'):
            self.assertContains(page, f'data-tz="{tz}"')
        self.assertContains(page, 'Holidays are not reflected')

    def test_marketaux_placeholder_slots_exist_without_fake_data(self):
        page = self.home()
        self.assertContains(page, 'data-slot="marketaux-news"')
        self.assertContains(page, 'data-slot="marketaux-prices"')
        self.assertNotContains(page, 'api.marketaux.com')

    def test_home_has_no_emoji_icons_and_header_is_accessible(self):
        page = self.home().content.decode()
        self.assertIn('class="skip-link"', page)
        self.assertIn('id="site-search"', page)
        self.assertIn('aria-label="Search"', page)
        for emoji in ('🔒', '📈', '🔔', '⭐'):
            self.assertNotIn(emoji, page)

    def test_header_shows_new_post_and_unread_count_for_members(self):
        Notification.objects.create(recipient=self.alice, notification_type='comment', message='hi')
        self.login(self.alice)
        page = self.home()
        self.assertContains(page, 'New Post')
        self.assertContains(page, 'Notifications, 1 unread')
        self.client.logout()
        self.assertNotContains(self.home(), 'New Post')


class SidebarTests(BaseCase):
    """The persistent site-wide navigation sidebar in base.html (every page, not just the feed)."""

    def test_sidebar_appears_on_every_kind_of_page_not_just_home(self):
        post = self.post()
        for url in (reverse('home'), reverse('companies'), reverse('startups'),
                    post.get_absolute_url(), self.asset.get_absolute_url(), reverse('search')):
            page = self.client.get(url)
            self.assertContains(page, 'id="site-sidebar"', msg_prefix=url)
            self.assertContains(page, 'Global Markets', msg_prefix=url)  # a seeded category

    def test_sidebar_nav_marks_the_current_section(self):
        page = self.client.get(reverse('companies'))
        self.assertContains(page, 'href="/companies/" aria-current="page"')

    def test_sidebar_category_links_point_at_the_real_pages(self):
        page = self.client.get(reverse('home'))
        self.assertContains(page, f'href="{self.category.get_absolute_url()}"')

    def test_sidebar_categories_show_an_icon_each_including_unmapped_ones(self):
        Category.objects.create(name='Future Topic', slug='future-topic')
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn('#i-chart', page)  # self.category is 'nepse', mapped to chart
        self.assertIn('#i-hash', page)  # unmapped category falls back to the generic tag icon

    def test_sidebar_highlights_the_open_category_page(self):
        page = self.client.get(self.category.get_absolute_url())
        self.assertContains(page, f'href="{self.category.get_absolute_url()}" aria-current="page"')

    def test_sidebar_shows_followed_star_only_once_followed(self):
        self.login(self.alice)
        self.assertNotContains(self.client.get(reverse('home')), 'title="Following">★')
        self.client.post(reverse('toggle_category_follow', args=[self.category.slug]))
        self.assertContains(self.client.get(reverse('home')), 'title="Following">★')

    def test_sidebar_hides_members_only_links_when_logged_out(self):
        page = self.client.get(reverse('home'))
        self.assertNotContains(page, '>Following<')
        self.assertNotContains(page, '>Watchlists<')
        self.login(self.alice)
        page = self.client.get(reverse('home'))
        self.assertContains(page, '>Watchlists<')

    def test_sidebar_toggle_button_and_markup_present_for_mobile(self):
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn('id="sidebar-toggle"', page)
        self.assertIn('aria-controls="site-sidebar"', page)
        self.assertIn('id="sidebar-scrim"', page)
        self.assertIn('id="sidebar-close"', page)

    def test_home_page_no_longer_duplicates_navigation_in_its_own_right_column(self):
        # Regression: the feed/category nav used to live twice (home's own rail + the header).
        # It now lives once, globally, in the sidebar — the old per-page copy is gone.
        page = self.client.get(reverse('home')).content.decode()
        self.assertNotIn('rail-left', page)
        self.assertIn('Market hours', page)  # moved into the right rail, not dropped


class MarkdownPreviewTests(BaseCase):
    """The post/comment composer's live Markdown "Preview" tab (see static/js/rich-editor.js)."""

    def test_anonymous_cannot_use_preview(self):
        response = self.client.post(reverse('markdown_preview'), {'body': 'hello'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_get_is_not_allowed(self):
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse('markdown_preview')).status_code, 405)

    def test_preview_uses_the_same_sanitizer_as_a_published_post(self):
        self.login(self.alice)
        response = self.client.post(reverse('markdown_preview'), {'body': '**bold** <script>alert(1)</script>'})
        self.assertContains(response, '<strong>bold</strong>')
        self.assertNotContains(response, '<script>alert')

    def test_blank_body_shows_a_placeholder_not_empty_markup(self):
        self.login(self.alice)
        response = self.client.post(reverse('markdown_preview'), {'body': '   '})
        self.assertContains(response, 'Nothing to preview yet.')
        self.assertNotContains(response, '<div class="prose">')

    def test_preview_is_rate_limited_per_member(self):
        self.login(self.alice)
        for _ in range(30):
            self.assertEqual(self.client.post(reverse('markdown_preview'), {'body': 'hi'}).status_code, 200)
        self.assertEqual(self.client.post(reverse('markdown_preview'), {'body': 'hi'}).status_code, 429)
        # A different member is not affected by alice's limit.
        self.login(self.bob)
        self.assertEqual(self.client.post(reverse('markdown_preview'), {'body': 'hi'}).status_code, 200)

    def test_editor_is_wired_up_on_pages_with_a_body_textarea(self):
        self.login(self.alice)
        page = self.client.get(reverse('create_post')).content.decode()
        self.assertIn('data-markdown-preview-url="/markdown/preview/"', page)
        self.assertIn('id="i-bold"', page)  # toolbar icon sprite present
        post = self.post()
        self.assertIn('data-markdown-preview-url', self.client.get(post.get_absolute_url()).content.decode())


class PromoBannerTests(BaseCase):
    """The dismissible "Join the discussion" banner shown above the header to signed-out visitors."""

    def test_shown_to_anonymous_visitors_on_any_page(self):
        post = self.post()
        for url in (reverse('home'), reverse('companies'), post.get_absolute_url()):
            page = self.client.get(url)
            self.assertContains(page, 'id="promo-banner"', msg_prefix=url)
            self.assertContains(page, 'Join the discussion', msg_prefix=url)

    def test_hidden_once_logged_in(self):
        self.login(self.alice)
        self.assertNotContains(self.client.get(reverse('home')), 'id="promo-banner"')

    def test_signup_link_links_to_signup(self):
        page = self.client.get(reverse('home'))
        self.assertContains(page, f'href="{reverse("signup")}"')

    def test_close_button_present_and_labelled(self):
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn('id="promo-banner-close"', page)
        self.assertIn('aria-label="Dismiss"', page)


class ThreadListHtmxNavigationTests(BaseCase):
    """Two separate htmx-powered swap zones:

    1. Section-level navigation (top nav, sidebar nav list + categories, bottom nav) swaps the
       whole #app-shell (header + sidebar + main + bottom-nav) as one unit. That's what keeps the
       chrome's aria-current state in sync across all three navs with a single swap, instead of
       juggling out-of-band swaps for each — htmx's hx-select-oob with more than one id in the
       list reprocesses targets multiple times (confirmed via htmx:oobAfterSwap firing 2x/3x/4x
       for a 3-id list) and leaves stale state, so OOB is deliberately avoided for this case.
    2. Within the home feed, switching tabs/category chips only swaps #feed-results (with a
       skeleton while in flight) plus a single #site-sidebar OOB swap for its own active state —
       see home.html.
    """

    def test_post_list_renders_a_skeleton_alongside_the_real_list(self):
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn('id="thread-skeleton"', page)
        self.assertIn('id="thread-list"', page)
        # The skeleton must come first so the CSS sibling rule (`.htmx-request ~ #thread-list`)
        # can hide the real list while the skeleton is shown.
        self.assertLess(page.index('id="thread-skeleton"'), page.index('id="thread-list"'))

    def test_sidebar_category_link_swaps_the_whole_app_shell_via_htmx(self):
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn(
            f'href="{self.category.get_absolute_url()}" hx-get="{self.category.get_absolute_url()}" '
            'hx-target="#app-shell" hx-select="#app-shell"',
            page,
        )
        self.assertIn('hx-push-url="true" hx-indicator="#thread-skeleton"', page)

    def test_sidebar_feed_links_also_use_htmx(self):
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn(f'hx-get="{reverse("home")}?tab=trending" hx-target="#app-shell"', page)
        self.assertIn(f'hx-get="{reverse("home")}?type=thesis" hx-target="#app-shell"', page)

    def test_feed_and_home_are_not_active_when_a_sub_tab_is(self):
        # All of Feed/Trending/Following/Theses/AMAs share url_name == 'home', only distinguished
        # by query params. "Feed" must not keep showing active once a sub-tab query param is set,
        # in the sidebar, the top nav or the bottom nav — otherwise two nav items look active at
        # once after an app-shell swap.
        for query in ['?tab=trending', '?tab=following', '?type=thesis', '?type=ama']:
            page = self.client.get(reverse('home') + query).content.decode()
            # Scoped to class="sidebar-nav", not the whole #site-sidebar — the sidebar also has a
            # brand/logo link to home earlier in the markup that never carries aria-current, which
            # would make this assertion trivially true even if the real Feed link were still active.
            sidebar = page[page.index('class="sidebar-nav"'):page.index('</nav>', page.index('class="sidebar-nav"'))]
            feed_link = sidebar[sidebar.index(f'href="{reverse("home")}"'):sidebar.index('</a>', sidebar.index(f'href="{reverse("home")}"'))]
            self.assertNotIn('aria-current="page"', feed_link, f'Feed wrongly active for {query}')
            primary_nav = page[page.index('id="primary-nav"'):page.index('</nav>', page.index('id="primary-nav"'))]
            home_link = primary_nav[primary_nav.index(f'href="{reverse("home")}"'):primary_nav.index('</a>', primary_nav.index(f'href="{reverse("home")}"'))]
            self.assertNotIn('aria-current="page"', home_link, f'top-nav Home wrongly active for {query}')

    def test_sidebar_company_and_startup_links_also_use_htmx(self):
        # These aren't thread lists, but they're still a full section switch — they must swap
        # the app shell via htmx too, not trigger a full-page reload that flashes the header/sidebar.
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn(f'href="{reverse("companies")}" hx-get="{reverse("companies")}" hx-target="#app-shell"', page)
        self.assertIn(f'href="{reverse("startups")}" hx-get="{reverse("startups")}" hx-target="#app-shell"', page)

    def test_top_nav_and_bottom_nav_links_use_htmx_too(self):
        # The top nav and the mobile bottom nav are the other two places a visitor switches
        # sections from — they need the same app-shell swap, or the navbar/sidebar still flash
        # on every click from those spots.
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn('id="app-shell"', page)
        self.assertIn('id="primary-nav"', page)
        self.assertIn('id="bottom-nav"', page)
        primary_nav = page[page.index('id="primary-nav"'):page.index('</nav>', page.index('id="primary-nav"'))]
        self.assertIn(f'hx-get="{reverse("companies")}" hx-target="#app-shell"', primary_nav)
        self.assertIn(f'hx-get="{reverse("news_list")}" hx-target="#app-shell"', primary_nav)
        bottom_nav = page[page.index('id="bottom-nav"'):]
        self.assertIn(f'hx-get="{reverse("home")}" hx-target="#app-shell"', bottom_nav)

    def test_no_section_nav_link_relies_on_multi_id_oob_swaps(self):
        # hx-select-oob with several comma-separated ids is the thing that broke active-state
        # sync (see class docstring) — guard against it creeping back in for any of these links.
        page = self.client.get(reverse('home')).content.decode()
        self.assertNotIn('hx-select-oob="#site-sidebar,#primary-nav,#bottom-nav"', page)
        self.assertNotIn('hx-select-oob="#site-sidebar,#bottom-nav"', page)

    def test_auth_pages_are_not_boosted(self):
        # login/signup render on a different base template with no header/sidebar/bottom-nav at
        # all — boosting them would swap #app-shell's content for a login form missing its own
        # chrome. They must stay ordinary links.
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn(f'<a class="hdr-link" href="{reverse("login")}">', page)
        self.assertNotIn(f'hx-get="{reverse("login")}"', page)
        self.assertNotIn(f'hx-get="{reverse("signup")}"', page)

    def test_home_tabs_and_chips_target_feed_results(self):
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn('id="feed-results"', page)
        self.assertIn('hx-target="#feed-results" hx-select="#feed-results"', page)
        self.assertIn(f'category={self.category.slug}" hx-get=', page.replace('&amp;', '&'))

    def test_category_page_swap_brings_the_category_panel_and_list_together(self):
        # Both live inside #main, so switching categories via the sidebar can't show a stale
        # title/description next to a freshly-loaded list (or vice versa).
        page = self.client.get(self.category.get_absolute_url()).content.decode()
        main_start = page.index('id="main"')
        self.assertLess(main_start, page.index(f'<h1>{self.category.name}</h1>'))
        self.assertLess(page.index(f'<h1>{self.category.name}</h1>'), page.index('id="thread-list"'))

    def test_app_shell_swap_response_shows_every_nav_in_sync(self):
        # Since the sidebar, top nav and bottom nav are swapped together with #main as one unit,
        # a Home page response must independently show Home active in all three — not just on the
        # triggering link, but in the actual markup that lands in each nav. (Bottom nav only has
        # Home/Search entries, so Home is the one link present in all three navs to check.)
        page = self.client.get(reverse('home')).content.decode()
        self.assertIn('id="app-shell"', page)
        primary_nav = page[page.index('id="primary-nav"'):page.index('</nav>', page.index('id="primary-nav"'))]
        # Scoped to class="sidebar-nav", not the whole #site-sidebar — the sidebar also has a
        # brand/logo link to home earlier in the markup that never carries aria-current.
        sidebar = page[page.index('class="sidebar-nav"'):page.index('</nav>', page.index('class="sidebar-nav"'))]
        bottom_nav = page[page.index('id="bottom-nav"'):]
        for fragment, label in [(primary_nav, 'primary-nav'), (sidebar, 'sidebar'), (bottom_nav, 'bottom-nav')]:
            home_link = fragment[fragment.index(f'href="{reverse("home")}"'):]
            self.assertIn('aria-current="page"', home_link[:200], f'{label} did not mark Home active')

    def test_home_tab_click_response_includes_a_correctly_updated_sidebar_fragment(self):
        # End-to-end: the response to an htmx navigation must contain an out-of-band #site-sidebar
        # fragment, with the clicked destination correctly marked current there too — not just as
        # an attribute on the triggering link, but in the actual swapped-in markup.
        response = self.client.get(self.category.get_absolute_url(), HTTP_HX_REQUEST='true', HTTP_HX_TARGET='main')
        body = response.content.decode()
        self.assertIn('id="site-sidebar"', body)
        sidebar = body[body.index('id="site-sidebar"'):]
        category_link = sidebar[sidebar.index(f'href="{self.category.get_absolute_url()}"'):]
        self.assertIn('aria-current="page"', category_link[:300])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class NewsTests(BaseCase):
    """Staff-written market news: square image tiles, only staff can post/edit/delete, everyone
    can read. Distinct from the user-generated "Market News" discussion category."""

    def news(self, **kwargs):
        defaults = {'title': 'NEPSE rallies on foreign buying', 'body': 'Full story.', 'author': self.staff, 'image': make_test_image()}
        defaults.update(kwargs)
        return NewsPost.objects.create(**defaults)

    def test_list_and_detail_are_public(self):
        article = self.news()
        self.assertEqual(self.client.get(reverse('news_list')).status_code, 200)
        self.assertEqual(self.client.get(article.get_absolute_url()).status_code, 200)

    def test_list_renders_title_as_an_image_background_tile(self):
        article = self.news(title='Markets close higher')
        page = self.client.get(reverse('news_list'))
        self.assertContains(page, 'class="news-card"')
        self.assertContains(page, f"background-image:url('{article.image.url}')")
        self.assertContains(page, 'Markets close higher')

    def test_slug_is_generated_from_title_and_deduplicated(self):
        first = self.news(title='Rate hike expected')
        second = self.news(title='Rate hike expected')
        self.assertEqual(first.slug, 'rate-hike-expected')
        self.assertEqual(second.slug, 'rate-hike-expected-2')

    def test_anonymous_cannot_see_or_reach_the_create_link(self):
        self.assertNotContains(self.client.get(reverse('news_list')), reverse('news_create'))
        response = self.client.get(reverse('news_create'))
        self.assertEqual(response.status_code, 302)  # login_required redirect

    def test_non_staff_member_is_forbidden_from_creating(self):
        self.login(self.alice)
        self.assertNotContains(self.client.get(reverse('news_list')), reverse('news_create'))
        self.assertEqual(self.client.get(reverse('news_create')).status_code, 403)
        response = self.client.post(reverse('news_create'), {'title': 'Hack', 'body': 'x', 'image': make_test_image()})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(NewsPost.objects.count(), 0)

    def test_staff_can_create_edit_and_delete(self):
        self.login(self.staff)
        self.assertContains(self.client.get(reverse('news_list')), reverse('news_create'))

        create = self.client.post(reverse('news_create'), {
            'title': 'Budget announcement moves markets', 'summary': 'Short take.', 'body': 'Long story.',
            'image': make_test_image(),
        })
        article = NewsPost.objects.get(title='Budget announcement moves markets')
        self.assertRedirects(create, article.get_absolute_url())
        self.assertEqual(article.author, self.staff)

        edit = self.client.post(reverse('news_edit', args=[article.slug]), {
            'title': 'Budget announcement moves markets (updated)', 'summary': 'Short take.', 'body': 'Long story, revised.',
            'image': make_test_image('update.jpg'),
        })
        article.refresh_from_db()
        self.assertRedirects(edit, article.get_absolute_url())
        self.assertEqual(article.body, 'Long story, revised.')

        delete_page = self.client.get(reverse('news_delete', args=[article.slug]))
        self.assertContains(delete_page, article.title)
        self.client.post(reverse('news_delete', args=[article.slug]))
        self.assertFalse(NewsPost.objects.filter(pk=article.pk).exists())

    def test_image_is_required(self):
        self.login(self.staff)
        response = self.client.post(reverse('news_create'), {'title': 'No image here', 'body': 'x'})
        self.assertEqual(response.status_code, 200)  # redisplays the form with an error
        self.assertFalse(NewsPost.objects.filter(title='No image here').exists())

    def test_nav_links_point_at_the_news_list_and_highlight_on_news_pages(self):
        article = self.news()
        home_page = self.client.get(reverse('home')).content.decode()
        self.assertIn(f'href="{reverse("news_list")}"', home_page)
        detail_page = self.client.get(article.get_absolute_url()).content.decode()
        self.assertIn(f'href="{reverse("news_list")}" aria-current="page"', detail_page)
