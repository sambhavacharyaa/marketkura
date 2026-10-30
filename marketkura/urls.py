from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.i18n import set_language

from community import views as community_views
from community.urls import api_patterns

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/setlang/', set_language, name='set_language'),
    path('api/', include(api_patterns)),
    # Custom login (throttled, username-or-email) and password reset take priority over Django's defaults.
    path('accounts/login/', community_views.ThrottledLoginView.as_view(), name='login'),
    path('accounts/password_reset/', community_views.ThrottledPasswordResetView.as_view(), name='password_reset'),
    path('accounts/', include('django.contrib.auth.urls')),
    # Google sign-in (django-allauth); the visible login and signup pages stay our own.
    path('auth/', include('allauth.urls')),
    path('', include('community.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
