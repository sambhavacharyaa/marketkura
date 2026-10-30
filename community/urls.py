from django.contrib.sitemaps.views import sitemap
from django.urls import path

from . import api, moderation, views
from .sitemaps import SITEMAPS

api_patterns = [
    path('auth/signup', api.SignupView.as_view(), name='api_signup'),
    path('auth/login', api.LoginView.as_view(), name='api_login'),
    path('categories/', api.CategoryListView.as_view(), name='api_categories'),
    path('posts/', api.PostListView.as_view(), name='api_posts'),
    path('posts/<int:pk>/', api.PostDetailView.as_view(), name='api_post_detail'),
    path('posts/<int:pk>/comments/', api.CommentListView.as_view(), name='api_post_comments'),
    path('posts/<int:pk>/upvote', api.UpvoteView.as_view(), name='api_post_upvote'),
    path('users/<str:username>/', api.UserDetailView.as_view(), name='api_user'),
    path('verification/apply', api.VerificationApplyView.as_view(), name='api_verification_apply'),
    path('tags/<str:slug>/posts', api.TagPostsView.as_view(), name='api_tag_posts'),
    path('reports/', api.ReportCreateView.as_view(), name='api_reports'),
]

urlpatterns = [
    path('', views.home, name='home'),
    path('posts/', views.posts, name='posts'),
    path('category/<slug:slug>/', views.category_detail, name='category_detail'),
    path('category/<slug:slug>/follow/', views.toggle_category_follow, name='toggle_category_follow'),

    # Posts: /post/<title-slug>-<id>/ is canonical; /post/<id>/ redirects to it.
    path('post/new/', views.create_post, name='create_post'),
    path('post/<str:slug>/', views.post_detail, name='post_detail'),
    path('post/<int:pk>/edit/', views.edit_post, name='edit_post'),
    path('post/<int:pk>/delete/', views.delete_post, name='delete_post'),
    path('post/<int:pk>/comment/', views.add_comment, name='add_comment'),
    path('post/<int:pk>/vote/', views.toggle_post_vote, name='toggle_post_vote'),
    path('post/<int:post_pk>/report/', views.report_content, name='report_post'),
    path('comment/<int:pk>/edit/', views.edit_comment, name='edit_comment'),
    path('comment/<int:pk>/delete/', views.delete_comment, name='delete_comment'),
    path('comment/<int:pk>/vote/', views.toggle_comment_vote, name='toggle_comment_vote'),
    path('comment/<int:comment_pk>/report/', views.report_content, name='report_comment'),

    path('signup/', views.signup, name='signup'),
    path('settings/', views.account_settings, name='settings'),
    path('u/<str:username>/', views.profile, name='profile'),
    path('u/<str:username>/follow/', views.toggle_follow, name='toggle_follow'),

    path('companies/', views.companies, name='companies'),
    path('companies/<str:ticker>/', views.company_legacy_redirect, name='company_legacy'),
    path('company/<str:slug>/', views.company_detail, name='company_detail'),
    path('company/<str:slug>/watchlist/', views.add_company_to_watchlist, name='add_company_to_watchlist'),

    path('watchlists/', views.watchlists, name='watchlists'),
    path('watchlists/<int:pk>/', views.watchlist_detail, name='watchlist_detail'),
    path('watchlists/<int:pk>/rename/', views.rename_watchlist, name='rename_watchlist'),
    path('watchlists/<int:pk>/delete/', views.delete_watchlist, name='delete_watchlist'),
    path('watchlists/<int:pk>/add/', views.add_watchlist_asset, name='add_watchlist_asset'),
    path('watchlists/<int:pk>/items/<int:item_pk>/remove/', views.remove_watchlist_asset, name='remove_watchlist_asset'),

    path('verification/apply/', views.verification_apply, name='verification_apply'),
    path('verification/status/', views.verification_status, name='verification_status'),
    path('verification/review/', views.verification_dashboard, name='verification_dashboard'),
    path('verification/review/<int:pk>/', views.review_verification, name='review_verification'),

    path('notifications/', views.notifications, name='notifications'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/read-all/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('search/', views.search, name='search'),
    path('markdown/preview/', views.markdown_preview, name='markdown_preview'),

    path('startups/', views.startups, name='startups'),
    path('startups/new/', views.startup_create, name='startup_create'),
    path('startups/<slug:slug>/', views.startup_detail, name='startup_detail'),
    path('startups/<slug:slug>/edit/', views.startup_edit, name='startup_edit'),

    path('news/', views.news_list, name='news_list'),
    path('news/new/', views.news_create, name='news_create'),
    path('news/<slug:slug>/', views.news_detail, name='news_detail'),
    path('news/<slug:slug>/edit/', views.news_edit, name='news_edit'),
    path('news/<slug:slug>/delete/', views.news_delete, name='news_delete'),

    path('moderation/', moderation.moderation_dashboard, name='moderation_dashboard'),
    path('moderation/action/', moderation.moderation_action, name='moderation_action'),
    path('moderation/startups/<int:pk>/approve/', moderation.approve_startup, name='approve_startup'),

    path('guidelines/', views.guidelines, name='guidelines'),
    path('disclaimer/', views.disclaimer, name='disclaimer'),
    path('privacy/', views.privacy, name='privacy'),
    path('terms/', views.terms, name='terms'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('robots.txt', views.robots_txt, name='robots'),
    path('sitemap.xml', sitemap, {'sitemaps': SITEMAPS}, name='sitemap'),
]
