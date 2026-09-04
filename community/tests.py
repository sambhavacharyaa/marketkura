from django.test import TestCase
from django.urls import reverse

from .models import Category, Comment, Post, PostVote, User


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
