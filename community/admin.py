from django.contrib import admin

from .models import Category, Comment, Post, PostVote, Report, Tag, User


admin.site.register(User)
admin.site.register(Category)
admin.site.register(Tag)
admin.site.register(Post)
admin.site.register(Comment)
admin.site.register(PostVote)
admin.site.register(Report)
