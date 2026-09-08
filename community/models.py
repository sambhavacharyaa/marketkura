from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class User(AbstractUser):
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    karma_score = models.IntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    verified_type = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.username


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Post(models.Model):
    POST_TYPES = [
        ('discussion', 'Discussion'),
        ('thesis', 'Thesis'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posts')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='posts')
    asset = models.ForeignKey('Tag', null=True, blank=True, on_delete=models.SET_NULL, related_name='asset_posts')
    type = models.CharField(max_length=20, choices=POST_TYPES, default='discussion')
    title = models.CharField(max_length=255)
    body = models.TextField()
    asset_tag = models.CharField(max_length=100, blank=True)
    thesis_entry = models.TextField(blank=True)
    thesis_risk = models.TextField(blank=True)
    position_type = models.CharField(max_length=12, choices=[('long', 'Long'), ('short', 'Short'), ('watching', 'Watching')], blank=True)
    entry_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    target_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    stop_loss = models.CharField(max_length=255, blank=True)
    time_horizon = models.CharField(max_length=12, choices=[('short', 'Short term'), ('medium', 'Medium term'), ('long', 'Long term')], blank=True)
    disclosure = models.TextField(blank=True)
    upvotes = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['type', '-created_at']), models.Index(fields=['asset', '-created_at'])]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('post_detail', args=[self.pk])


class PostVote(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='post_votes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['post', 'user'], name='unique_post_vote'),
        ]


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comments')
    parent_comment = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='replies')
    body = models.TextField()
    upvotes = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user.username} on {self.post.title}'


class Tag(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    ticker = models.CharField(max_length=20, unique=True, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        return self.company_name or self.name


class PostTag(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='tags')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='posts')

    class Meta:
        unique_together = ('post', 'tag')


class Watchlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='watchlists')
    name = models.CharField(max_length=100, default='My Watchlist')
    # Retained temporarily for compatibility with Phase 1 data; new items live in WatchlistItem.
    tag = models.ForeignKey(Tag, null=True, blank=True, on_delete=models.SET_NULL, related_name='legacy_watchers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'name'], name='unique_watchlist_name_per_user')]
        indexes = [models.Index(fields=['user', 'created_at'])]

    def __str__(self):
        return f'{self.user.username}: {self.name}'


class WatchlistItem(models.Model):
    watchlist = models.ForeignKey(Watchlist, on_delete=models.CASCADE, related_name='items')
    asset = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='watchlist_items')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['watchlist', 'asset'], name='unique_asset_per_watchlist')]
        indexes = [models.Index(fields=['watchlist', 'asset'])]


class VerificationRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [(STATUS_PENDING, 'Pending'), (STATUS_APPROVED, 'Approved'), (STATUS_REJECTED, 'Rejected')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='verification_requests')
    full_name = models.CharField(max_length=255, blank=True)
    application_reason = models.TextField(blank=True)
    areas_of_expertise = models.TextField(blank=True)
    experience = models.TextField(blank=True)
    supporting_information = models.TextField(blank=True)
    website_url = models.URLField(blank=True)
    credentials_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='verified_reviews')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']


class Notification(models.Model):
    TYPES = [
        ('comment', 'Comment'), ('reply', 'Reply'), ('reaction', 'Reaction'),
        ('verification_approved', 'Verification approved'), ('verification_rejected', 'Verification rejected'),
        ('mention', 'Mention'), ('follow', 'Follow'),
    ]
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='actions')
    notification_type = models.CharField(max_length=32, choices=TYPES)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    target_url = models.CharField(max_length=500, blank=True)
    message = models.CharField(max_length=500)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['recipient', 'is_read', '-created_at'])]


class Report(models.Model):
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.SET_NULL, related_name='reports')
    comment = models.ForeignKey('Comment', null=True, blank=True, on_delete=models.SET_NULL, related_name='reports')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_made')
    reason = models.TextField()
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
