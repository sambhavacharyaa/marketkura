from django.test import TestCase
from django.urls import reverse

from .models import (Category, Comment, Notification, Post, PostVote, Tag, User,
                     VerificationRequest, Watchlist, WatchlistItem)


class CommunityViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='trader',
            email='trader@example.com',
            password='testpass123',
        )
        self.category = Category.objects.create(
            name='Nepse',
            slug='nepse',
            description='Nepal stock market discussion.',
        )

    def test_home_page_renders(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_post_can_be_created(self):
        post = Post.objects.create(
            user=self.user,
            category=self.category,
            title='NEPSE sentiment thread',
            body='Strong momentum in banking stocks.',
            type='discussion',
        )
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(post.title, 'NEPSE sentiment thread')

    def test_signup_creates_and_logs_in_user(self):
        response = self.client.post(reverse('signup'), {
            'username': 'new-member',
            'email': 'new@example.com',
            'password1': 'a-strong-password-123',
            'password2': 'a-strong-password-123',
        })
        self.assertRedirects(response, reverse('home'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_authenticated_member_can_create_comment_and_vote(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('create_post'), {
            'category': self.category.pk,
            'type': 'discussion',
            'title': 'Banking sector discussion',
            'body': 'What are you watching this week?',
            'asset_tag': 'NEPSE',
            'thesis_entry': '',
            'thesis_risk': '',
        })
        post = Post.objects.get(title='Banking sector discussion')
        self.assertRedirects(response, reverse('post_detail', args=[post.pk]))

        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'Following this thread.'})
        self.client.post(reverse('toggle_post_vote', args=[post.pk]))
        self.assertEqual(Comment.objects.filter(post=post).count(), 1)
        self.assertEqual(PostVote.objects.filter(post=post, user=self.user).count(), 1)
        self.assertEqual(Post.objects.get(pk=post.pk).upvotes, 1)

    def test_home_search_filters_posts(self):
        Post.objects.create(user=self.user, category=self.category, title='NEPSE banking', body='Local market')
        Post.objects.create(user=self.user, category=self.category, title='Global technology', body='US markets')
        response = self.client.get(reverse('home'), {'q': 'NEPSE'})
        self.assertContains(response, 'NEPSE banking')
        self.assertNotContains(response, 'Global technology')


class PhaseTwoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='member', password='pass12345')
        self.other = User.objects.create_user(username='other', password='pass12345')
        self.staff = User.objects.create_superuser(username='staff', email='staff@example.com', password='pass12345')
        self.category = Category.objects.create(name='Stocks', slug='stocks')
        self.asset = Tag.objects.create(name='NABIL', slug='nabil', ticker='NABIL', company_name='Nabil Bank Limited')

    def post_data(self, **overrides):
        data = {'category': self.category.pk, 'type': 'thesis', 'title': 'NABIL thesis', 'body': 'Improving earnings and fundamentals.', 'asset': self.asset.pk, 'asset_tag': '', 'position_type': 'long', 'entry_price': '520', 'target_price': '650', 'stop_loss': '', 'time_horizon': 'medium', 'thesis_risk': '', 'disclosure': ''}
        data.update(overrides)
        return data

    def create_post(self, **kwargs):
        return Post.objects.create(user=self.user, category=self.category, **kwargs)

    def test_thesis_create_validation_and_edit_permissions(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('create_post'), self.post_data())
        self.assertEqual(response.status_code, 302)
        thesis = Post.objects.get(type='thesis')
        self.assertEqual(thesis.entry_price, 520)
        self.assertEqual(thesis.asset, self.asset)
        self.assertContains(self.client.get(reverse('post_detail', args=[thesis.pk])), 'Self-reported thesis')
        self.assertContains(self.client.post(reverse('create_post'), self.post_data(title='Bad', entry_price='-1')), 'Entry price must be positive')
        self.assertContains(self.client.post(reverse('create_post'), self.post_data(title='Bad target', target_price='0')), 'Target price must be positive')
        self.assertContains(self.client.post(reverse('create_post'), self.post_data(title='No body', body='')), 'A thesis body is required')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('edit_post', args=[thesis.pk])).status_code, 403)
        self.client.force_login(self.user)
        response = self.client.post(reverse('edit_post', args=[thesis.pk]), self.post_data(title='Updated thesis'))
        self.assertEqual(response.status_code, 302)
        thesis.refresh_from_db(); self.assertEqual(thesis.title, 'Updated thesis')

    def test_discussion_post_can_be_created(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('create_post'), self.post_data(type='discussion', title='Discussion', entry_price='', target_price='', position_type='', time_horizon=''))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Post.objects.get(title='Discussion').type, 'discussion')

    def test_watchlist_crud_and_private_access(self):
        self.client.force_login(self.user)
        self.client.post(reverse('watchlists'), {'name': 'Banks'})
        watchlist = Watchlist.objects.get(user=self.user)
        self.client.post(reverse('add_watchlist_asset', args=[watchlist.pk]), {'asset': self.asset.pk})
        self.client.post(reverse('add_watchlist_asset', args=[watchlist.pk]), {'asset': self.asset.pk})
        self.assertEqual(WatchlistItem.objects.count(), 1)
        item = watchlist.items.get()
        self.client.post(reverse('remove_watchlist_asset', args=[watchlist.pk, item.pk]))
        self.assertEqual(watchlist.items.count(), 0)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('watchlist_detail', args=[watchlist.pk])).status_code, 404)
        self.client.force_login(self.user)
        self.client.post(reverse('delete_watchlist', args=[watchlist.pk]))
        self.assertFalse(Watchlist.objects.filter(pk=watchlist.pk).exists())

    def test_verification_review_and_badge(self):
        self.client.force_login(self.user)
        payload = {'full_name': 'Member Name', 'application_reason': 'I contribute research.', 'areas_of_expertise': 'Banks', 'experience': 'Five years', 'supporting_information': 'Writing samples', 'website_url': ''}
        self.assertEqual(self.client.post(reverse('verification_apply'), payload).status_code, 302)
        self.assertContains(self.client.get(reverse('verification_status')), 'Pending')
        self.assertEqual(self.client.post(reverse('verification_apply'), payload).status_code, 302)
        self.assertEqual(VerificationRequest.objects.count(), 1)
        application = VerificationRequest.objects.get()
        self.client.force_login(self.other)
        self.client.post(reverse('review_verification', args=[application.pk]), {'action': 'approve'})
        application.refresh_from_db(); self.assertEqual(application.status, 'pending')
        self.client.force_login(self.staff)
        self.client.post(reverse('review_verification', args=[application.pk]), {'action': 'approve'})
        self.user.refresh_from_db(); application.refresh_from_db()
        self.assertTrue(self.user.is_verified); self.assertEqual(application.status, 'approved')
        self.assertTrue(Notification.objects.filter(recipient=self.user, notification_type='verification_approved').exists())
        self.assertContains(self.client.get(reverse('profile', args=[self.user.username])), 'Verified Contributor')

    def test_rejection_reason_and_company_filters_seo(self):
        application = VerificationRequest.objects.create(user=self.user, full_name='Member')
        self.client.force_login(self.staff)
        self.client.post(reverse('review_verification', args=[application.pk]), {'action': 'reject', 'rejection_reason': 'Need more supporting information.'})
        application.refresh_from_db(); self.assertEqual(application.rejection_reason, 'Need more supporting information.')
        self.create_post(type='discussion', title='NABIL discussion', body='Discussion', asset=self.asset)
        self.create_post(type='thesis', title='NABIL thesis', body='Thesis', asset=self.asset, position_type='long', entry_price='100', time_horizon='long')
        response = self.client.get(reverse('company_detail', args=['NABIL']), {'section': 'theses'})
        self.assertContains(response, 'NABIL thesis'); self.assertNotContains(response, 'NABIL discussion')
        self.assertContains(response, 'canonical'); self.assertContains(response, 'og:title')
        response = self.client.get(reverse('company_detail', args=['NABIL']), {'section': 'discussions'})
        self.assertContains(response, 'NABIL discussion'); self.assertNotContains(response, 'NABIL thesis')

    def test_post_filters_and_pagination(self):
        for number in range(13):
            self.create_post(type='thesis' if number == 0 else 'discussion', title=f'Post {number}', body='Body', asset=self.asset,
                position_type='long' if number == 0 else '', entry_price='20' if number == 0 else None, time_horizon='long' if number == 0 else '')
        response = self.client.get(reverse('posts'), {'type': 'thesis', 'asset': 'NABIL', 'position': 'long', 'horizon': 'long'})
        self.assertContains(response, 'Post 0'); self.assertNotContains(response, 'Post 1')
        response = self.client.get(reverse('company_detail', args=['NABIL']), {'page': 2})
        self.assertContains(response, 'Page 2 of 2')

    def test_notifications_and_search(self):
        post = self.create_post(type='discussion', title='Why NABIL', body='Bank view', asset=self.asset)
        self.client.force_login(self.other)
        self.client.post(reverse('add_comment', args=[post.pk]), {'body': 'I agree @member'})
        self.assertGreaterEqual(Notification.objects.filter(recipient=self.user).count(), 2)
        notification = Notification.objects.filter(recipient=self.user).first()
        self.client.force_login(self.user)
        self.client.post(reverse('mark_notification_read', args=[notification.pk]))
        notification.refresh_from_db(); self.assertTrue(notification.is_read)
        self.client.post(reverse('mark_all_notifications_read'))
        self.assertFalse(Notification.objects.filter(recipient=self.user, is_read=False).exists())
        response = self.client.get(reverse('search'), {'q': 'nabil'})
        self.assertContains(response, 'Nabil Bank Limited'); self.assertContains(response, 'Why NABIL')
        self.assertContains(self.client.get(reverse('search'), {'q': 'MEMBER'}), '@member')
        self.assertEqual(self.client.get(reverse('search')).status_code, 200)
        for number in range(13): self.create_post(type='discussion', title=f'Extra {number}', body='Search body', asset=self.asset)
        self.assertContains(self.client.get(reverse('search'), {'q': 'search', 'page': 2}), 'Page 2 of 2')
