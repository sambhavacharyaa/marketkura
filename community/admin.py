from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils import timezone

from .models import (Category, CategoryFollow, Comment, CommentVote, ContactMessage, Follow, NewsPost, Notification,
                     Post, PostTag, PostVote, Report, StartupProfile, Tag, User, VerificationRequest, Watchlist,
                     WatchlistItem)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ('username', 'email', 'karma_score', 'is_verified', 'is_shadow_banned', 'is_staff', 'date_joined')
    list_filter = ('is_verified', 'is_shadow_banned', 'is_staff')
    search_fields = ('username', 'email')
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('MarketKuraa', {'fields': ('bio', 'avatar', 'karma_score', 'is_verified', 'verified_type', 'is_shadow_banned')}),
    )
    actions = ['shadow_ban', 'lift_shadow_ban']

    @admin.action(description='Shadow-ban selected members')
    def shadow_ban(self, request, queryset):
        updated = queryset.filter(is_staff=False).update(is_shadow_banned=True)
        self.message_user(request, f'{updated} member(s) shadow-banned.')

    @admin.action(description='Lift shadow-ban on selected members')
    def lift_shadow_ban(self, request, queryset):
        self.message_user(request, f'{queryset.update(is_shadow_banned=False)} member(s) restored.')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'min_karma', 'requires_verified')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'ticker', 'company_name', 'is_company')
    list_filter = ('is_company',)
    search_fields = ('name', 'ticker', 'company_name')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'category', 'type', 'is_locked', 'is_removed', 'created_at')
    list_filter = ('type', 'category', 'is_locked', 'is_removed')
    search_fields = ('title', 'body', 'user__username')
    actions = ['lock', 'unlock', 'remove', 'restore']

    @admin.action(description='Lock selected threads')
    def lock(self, request, queryset):
        queryset.update(is_locked=True)

    @admin.action(description='Unlock selected threads')
    def unlock(self, request, queryset):
        queryset.update(is_locked=False)

    @admin.action(description='Remove selected posts (hidden from the site)')
    def remove(self, request, queryset):
        queryset.update(is_removed=True)

    @admin.action(description='Restore selected posts')
    def restore(self, request, queryset):
        queryset.update(is_removed=False)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'is_removed', 'created_at')
    list_filter = ('is_removed',)
    search_fields = ('body', 'user__username')
    actions = ['remove', 'restore']

    @admin.action(description='Remove selected comments')
    def remove(self, request, queryset):
        queryset.update(is_removed=True)

    @admin.action(description='Restore selected comments')
    def restore(self, request, queryset):
        queryset.update(is_removed=False)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'is_resolved', 'created_at')
    list_filter = ('is_resolved',)
    list_editable = ('is_resolved',)
    search_fields = ('name', 'email', 'subject', 'message')
    readonly_fields = ('user', 'name', 'email', 'subject', 'message', 'created_at')


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'post', 'comment', 'status', 'created_at')
    list_filter = ('status', 'category')
    readonly_fields = ('created_at', 'reviewed_at', 'reviewed_by')
    actions = ['mark_actioned', 'mark_dismissed']

    def _resolve(self, request, queryset, status):
        queryset.filter(status=Report.STATUS_PENDING).update(status=status, reviewed_by=request.user, reviewed_at=timezone.now())

    @admin.action(description='Mark as action taken')
    def mark_actioned(self, request, queryset):
        self._resolve(request, queryset, Report.STATUS_ACTIONED)

    @admin.action(description='Dismiss')
    def mark_dismissed(self, request, queryset):
        self._resolve(request, queryset, Report.STATUS_DISMISSED)


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'requested_type', 'status', 'created_at', 'reviewed_by')
    list_filter = ('status', 'requested_type')
    search_fields = ('user__username', 'full_name', 'application_reason')
    readonly_fields = ('created_at', 'reviewed_at', 'reviewed_by')


@admin.register(StartupProfile)
class StartupProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'stage', 'sector', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'stage')
    search_fields = ('name', 'tagline', 'owner__username')
    prepopulated_fields = {'slug': ('name',)}
    actions = ['approve', 'unpublish']

    @admin.action(description='Approve and list selected startups')
    def approve(self, request, queryset):
        queryset.update(is_approved=True)

    @admin.action(description='Unpublish selected startups')
    def unpublish(self, request, queryset):
        queryset.update(is_approved=False)


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at')
    search_fields = ('name', 'user__username')


@admin.register(NewsPost)
class NewsPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'created_at')
    search_fields = ('title', 'body')
    prepopulated_fields = {'slug': ('title',)}


for model in (PostVote, CommentVote, PostTag, WatchlistItem, Notification, Follow, CategoryFollow):
    admin.site.register(model)
