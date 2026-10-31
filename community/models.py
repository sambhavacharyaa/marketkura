from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.utils.translation import get_language


EDITED_GRACE = timedelta(seconds=10)


class User(AbstractUser):
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    karma_score = models.IntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    verified_type = models.CharField(max_length=50, blank=True)
    # Shadow-ban: the account keeps working for its owner, but nobody else sees its content.
    is_shadow_banned = models.BooleanField(default=False)

    def __str__(self):
        return self.username

    def get_absolute_url(self):
        return reverse('profile', args=[self.username])

    @property
    def is_new_account(self):
        return self.date_joined > timezone.now() - timedelta(days=settings.NEW_ACCOUNT_DAYS)

    @property
    def verified_label(self):
        return self.verified_type or 'Verified Contributor'


class Follow(models.Model):
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='following')
    following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['follower', 'following'], name='unique_user_follow'),
            models.CheckConstraint(check=~Q(follower=models.F('following')), name='prevent_self_follow'),
        ]
        indexes = [models.Index(fields=['following', '-created_at'])]


# The six blueprint categories are seeded (0006_seed_categories) with English names, not a
# translatable model field — this map supplies the Nepali display name by slug instead. A
# category created later through the admin without an entry here just falls back to its stored
# (English) name, same graceful-fallback approach as CATEGORY_ICONS in community_extras.py.
CATEGORY_NAMES_NE = {
    'nepse': 'नेप्से',
    'global-markets': 'विश्वव्यापी बजार',
    'startups-founders': 'स्टार्टअप र संस्थापकहरू',
    'personal-finance': 'व्यक्तिगत फाइनान्स',
    'trading-strategy': 'ट्रेडिङ रणनीति',
    'market-news': 'बजार समाचार',
}


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    # High-trust sections: new or low-reputation accounts cannot start threads here yet.
    min_karma = models.PositiveIntegerField(default=0)
    requires_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        if get_language() == 'ne':
            return CATEGORY_NAMES_NE.get(self.slug, self.name)
        return self.name

    def get_absolute_url(self):
        return reverse('category_detail', args=[self.slug])

    @property
    def is_restricted(self):
        return self.min_karma > 0 or self.requires_verified


class CategoryFollow(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='category_follows')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'category'], name='unique_category_follow')]


class Tag(models.Model):
    """A company/ticker or a plain topic tag. Company pages are built from these."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, allow_unicode=True)
    ticker = models.CharField(max_length=20, unique=True, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    is_company = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        return self.company_name or self.name

    def get_absolute_url(self):
        return reverse('company_detail', args=[self.slug])


class Post(models.Model):
    TYPE_DISCUSSION = 'discussion'
    TYPE_THESIS = 'thesis'
    TYPE_AMA = 'ama'
    POST_TYPES = [
        (TYPE_DISCUSSION, _('Discussion')),
        (TYPE_THESIS, _('Thesis')),
        (TYPE_AMA, _('AMA')),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posts')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='posts')
    asset = models.ForeignKey(Tag, null=True, blank=True, on_delete=models.SET_NULL, related_name='asset_posts')
    type = models.CharField(max_length=20, choices=POST_TYPES, default=TYPE_DISCUSSION)
    title = models.CharField(max_length=255)
    body = models.TextField()
    image = models.ImageField(upload_to='posts/', null=True, blank=True)
    asset_tag = models.CharField(max_length=100, blank=True)
    thesis_entry = models.TextField(blank=True)
    thesis_risk = models.TextField(blank=True)
    position_type = models.CharField(max_length=12, choices=[('long', _('Long')), ('short', _('Short')), ('watching', _('Watching'))], blank=True)
    entry_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    target_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    stop_loss = models.CharField(max_length=255, blank=True)
    time_horizon = models.CharField(max_length=12, choices=[('short', _('Short term')), ('medium', _('Medium term')), ('long', _('Long term'))], blank=True)
    disclosure = models.TextField(blank=True)
    ama_starts_at = models.DateTimeField(null=True, blank=True)
    ama_ends_at = models.DateTimeField(null=True, blank=True)
    upvotes = models.IntegerField(default=0)  # net score: upvotes minus downvotes, kept denormalized for sorting
    is_locked = models.BooleanField(default=False)
    is_removed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['type', '-created_at']), models.Index(fields=['asset', '-created_at'])]

    def __str__(self):
        return self.title

    @property
    def url_slug(self):
        return f"{slugify(self.title, allow_unicode=True)[:60].strip('-') or 'post'}-{self.pk}"

    def get_absolute_url(self):
        return reverse('post_detail', args=[self.url_slug])

    @property
    def was_edited(self):
        # created_at and updated_at are stamped separately, so allow a little slack.
        return self.updated_at - self.created_at > EDITED_GRACE

    @property
    def ama_state(self):
        """'upcoming', 'live' or 'ended' for AMA posts; empty for everything else."""
        if self.type != self.TYPE_AMA:
            return ''
        now = timezone.now()
        if self.ama_starts_at and now < self.ama_starts_at:
            return 'upcoming'
        if self.ama_ends_at and now > self.ama_ends_at:
            return 'ended'
        return 'live'


class PostVote(models.Model):
    DIRECTION_UP = 'up'
    DIRECTION_DOWN = 'down'
    DIRECTION_CHOICES = [(DIRECTION_UP, _('Up')), (DIRECTION_DOWN, _('Down'))]

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='post_votes')
    direction = models.CharField(max_length=4, choices=DIRECTION_CHOICES, default=DIRECTION_UP)
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
    upvotes = models.IntegerField(default=0)  # net score: upvotes minus downvotes, kept denormalized for sorting
    is_removed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.user.username} on {self.post.title}'

    @property
    def was_edited(self):
        return self.updated_at - self.created_at > EDITED_GRACE

    def get_absolute_url(self):
        return f'{self.post.get_absolute_url()}#comment-{self.pk}'


class CommentVote(models.Model):
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comment_votes')
    direction = models.CharField(max_length=4, choices=PostVote.DIRECTION_CHOICES, default=PostVote.DIRECTION_UP)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['comment', 'user'], name='unique_comment_vote')]


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
    TYPE_CHOICES = [
        ('Verified Contributor', _('Contributor')),
        ('Verified Analyst', _('Analyst')),
        ('Verified Professional', _('Finance professional')),
        ('Verified Fund Manager', _('Fund manager')),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='verification_requests')
    requested_type = models.CharField(max_length=50, choices=TYPE_CHOICES, default='Verified Contributor')
    full_name = models.CharField(max_length=255, blank=True)
    application_reason = models.TextField(blank=True)
    areas_of_expertise = models.TextField(blank=True)
    experience = models.TextField(blank=True)
    supporting_information = models.TextField(blank=True)
    website_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    credentials_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='verified_reviews')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user'], condition=Q(status='pending'), name='one_pending_verification_per_user'
            ),
        ]

    def get_absolute_url(self):
        return reverse('review_verification', args=[self.pk])


class Notification(models.Model):
    TYPES = [
        ('comment', 'Comment'), ('reply', 'Reply'), ('reaction', 'Reaction'),
        ('verification_approved', 'Verification approved'), ('verification_rejected', 'Verification rejected'),
        ('mention', 'Mention'), ('follow', 'Follow'), ('moderation', 'Moderation'),
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
    STATUS_PENDING = 'pending'
    STATUS_ACTIONED = 'actioned'
    STATUS_DISMISSED = 'dismissed'
    STATUS_CHOICES = [(STATUS_PENDING, _('Pending')), (STATUS_ACTIONED, _('Action taken')), (STATUS_DISMISSED, _('Dismissed'))]
    CATEGORY_CHOICES = [
        ('spam', _('Spam or scam')),
        ('hype', _('Coordinated hype / pump-and-dump')),
        ('harassment', _('Harassment or abuse')),
        ('misinformation', _('Misleading or false claims')),
        ('other', _('Something else')),
    ]

    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.SET_NULL, related_name='reports')
    comment = models.ForeignKey('Comment', null=True, blank=True, on_delete=models.SET_NULL, related_name='reports')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_made')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reports_reviewed')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['reporter', 'post'], condition=Q(post__isnull=False), name='one_report_per_user_post'),
            models.UniqueConstraint(fields=['reporter', 'comment'], condition=Q(comment__isnull=False), name='one_report_per_user_comment'),
        ]

    def __str__(self):
        return f'Report by {self.reporter.username}: {self.get_category_display()}'


class StartupProfile(models.Model):
    """V2 founder/startup discovery. Profiles are listed only after staff approval."""

    STAGE_CHOICES = [
        ('idea', _('Idea')), ('pre_seed', _('Pre-seed')), ('seed', _('Seed')),
        ('growth', _('Growth')), ('profitable', _('Profitable')),
    ]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='startups')
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True, allow_unicode=True)
    tagline = models.CharField(max_length=200)
    description = models.TextField()
    sector = models.CharField(max_length=80, blank=True)
    stage = models.CharField(max_length=12, choices=STAGE_CHOICES, default='idea')
    location = models.CharField(max_length=120, blank=True)
    website_url = models.URLField(blank=True)
    looking_for = models.CharField(max_length=255, blank=True)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('startup_detail', args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=True)[:130] or 'startup'
            candidate, n = base, 2
            while StartupProfile.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate, n = f'{base}-{n}', n + 1
            self.slug = candidate
        super().save(*args, **kwargs)


class NewsPost(models.Model):
    """Staff-written market news. Distinct from the user-generated "Market News" discussion
    category — this is MarketKuraa's own editorial content, not a thread topic."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, allow_unicode=True, blank=True)
    image = models.ImageField(upload_to='news/')
    summary = models.CharField(max_length=300, blank=True)
    body = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='news_posts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('news_detail', args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title, allow_unicode=True)[:140] or 'news'
            candidate, n = base, 2
            while NewsPost.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate, n = f'{base}-{n}', n + 1
            self.slug = candidate
        super().save(*args, **kwargs)


class ContactMessage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='contact_messages')
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=150)
    message = models.TextField(max_length=5000)
    is_resolved = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} - {self.subject}'
