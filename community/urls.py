from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('category/<slug:slug>/', views.category_detail, name='category_detail'),
    path('post/<int:pk>/', views.post_detail, name='post_detail'),
    path('post/new/', views.create_post, name='create_post'),
    path('post/<int:pk>/comment/', views.add_comment, name='add_comment'),
    path('post/<int:pk>/vote/', views.toggle_post_vote, name='toggle_post_vote'),
    path('post/<int:pk>/report/', views.report_post, name='report_post'),
    path('signup/', views.signup, name='signup'),
    path('u/<str:username>/', views.profile, name='profile'),
]
