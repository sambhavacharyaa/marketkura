from django.test import TestCase
from django.urls import reverse

from .models import Category, Post, User


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
