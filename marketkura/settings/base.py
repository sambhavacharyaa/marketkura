"""Settings shared by all MarketKuraa environments."""

import os
from pathlib import Path

from dotenv import load_dotenv
from django.utils.translation import gettext_lazy as _


BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {'1', 'true', 'yes', 'on'}


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'django.contrib.humanize',
    'rest_framework',
    'rest_framework.authtoken',
    'django_htmx',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'community',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'marketkura.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.i18n',
                'community.context_processors.site',
                'community.context_processors.notification_counts',
                'community.context_processors.sidebar_nav',
            ],
        },
    },
]

WSGI_APPLICATION = 'marketkura.wsgi.application'
ASGI_APPLICATION = 'marketkura.asgi.application'

# --- Authentication -------------------------------------------------------
AUTH_USER_MODEL = 'community.User'
AUTHENTICATION_BACKENDS = [
    'community.backends.EmailOrUsernameBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Google sign-in is optional: it only appears when both values are set.
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
GOOGLE_LOGIN_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {'client_id': GOOGLE_CLIENT_ID, 'secret': GOOGLE_CLIENT_SECRET, 'key': ''},
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
    },
}
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
ACCOUNT_LOGIN_METHODS = {'username', 'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'none'

# --- Internationalisation (English + Nepali) --------------------------------
LANGUAGE_CODE = 'en'
LANGUAGES = [('en', _('English')), ('ne', _('नेपाली'))]
LOCALE_PATHS = [BASE_DIR / 'locale']
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# --- Static / media ---------------------------------------------------------
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '25'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', False)
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'MarketKuraa <noreply@marketkuraa.com>')

# --- REST API (blueprint section 12) --------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticatedOrReadOnly'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.ScopedRateThrottle'],
    'DEFAULT_THROTTLE_RATES': {'auth': '10/min', 'write': '60/min'},
}

# --- Community rules (blueprint sections 13, 19, and V2 unlocks) ----------
# New accounts are rate limited until they are NEW_ACCOUNT_DAYS old.
NEW_ACCOUNT_DAYS = 7
NEW_ACCOUNT_POSTS_PER_DAY = 3
NEW_ACCOUNT_COMMENTS_PER_DAY = 20
# Flag an asset when this many posts from this many distinct authors land within the window.
PUMP_WATCH_POSTS = 5
PUMP_WATCH_AUTHORS = 3
PUMP_WATCH_HOURS = 24
# Failed logins allowed per (ip, username) before a temporary lockout.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
SIGNUP_MAX_PER_HOUR = 5
CONTACT_MAX_PER_HOUR = 5
# Honeypot forms (signup, contact) reject a submission that arrives faster than this after the
# page rendered — a human can't plausibly read and fill the form that quickly.
FORM_MIN_SUBMIT_SECONDS = 3
# Karma needed to unlock features (verified members always qualify).
REPUTATION_UNLOCKS = {'startup_profile': 10}
# When true, the client IP is read from X-Forwarded-For (only enable behind a trusted proxy).
USE_X_FORWARDED_FOR = env_bool('USE_X_FORWARDED_FOR', False)

# --- Cloudflare Turnstile (optional) ---------------------------------------
# Unset in dev by default, so local signup/contact forms work without a Cloudflare account. Set
# both env vars in production to turn the widget on.
TURNSTILE_SITE_KEY = os.getenv('TURNSTILE_SITE_KEY', '')
TURNSTILE_SECRET_KEY = os.getenv('TURNSTILE_SECRET_KEY', '')

# Shows the "Live prices" and "Market news" placeholder widgets on the home feed. Off by default —
# a permanently-empty "coming soon" widget doesn't earn its space; turn it on once there's a real
# data source (e.g. Marketaux) wired up behind it.
SHOW_COMING_SOON_WIDGETS = env_bool('SHOW_COMING_SOON_WIDGETS', False)

SITE_NAME = 'MarketKuraa'
