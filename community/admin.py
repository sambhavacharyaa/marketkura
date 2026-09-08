from django.contrib import admin

from .models import (Category, Comment, Notification, Post, PostVote, Report, Tag,
                     User, VerificationRequest, Watchlist, WatchlistItem)


admin.site.register(User)
admin.site.register(Category)
admin.site.register(Tag)
admin.site.register(Post)
admin.site.register(Comment)
admin.site.register(PostVote)
admin.site.register(Report)


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'status', 'created_at', 'reviewed_by')
    list_filter = ('status',)
    search_fields = ('user__username', 'full_name', 'application_reason')
    readonly_fields = ('created_at', 'reviewed_at', 'reviewed_by')


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at')
    search_fields = ('name', 'user__username')


admin.site.register(WatchlistItem)
admin.site.register(Notification)
