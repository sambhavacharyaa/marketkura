"""Production settings for MarketKura."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403,F401
from .base import env_bool


def get_required_setting(name):
    value = os.getenv(name)
    if not value:
        raise ImproperlyConfigured(f'{name} must be set in production.')
    return value


def get_bool_setting(name, default=False):
    return env_bool(name, default)


DEBUG = False
SECRET_KEY = get_required_setting('DJANGO_SECRET_KEY')
ALLOWED_HOSTS = [
    host.strip()
    for host in get_required_setting('ALLOWED_HOSTS').split(',')
    if host.strip()
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': get_required_setting('DB_NAME'),
        'USER': get_required_setting('DB_USER'),
        'PASSWORD': get_required_setting('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

SECURE_SSL_REDIRECT = get_bool_setting('SECURE_SSL_REDIRECT', True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'

# Behind nginx/another TLS-terminating proxy, trust its forwarded-proto header.
if get_bool_setting('BEHIND_PROXY', False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Login throttling and rate limits need a cache shared by every worker. Use Redis
# when REDIS_URL is set, otherwise a database cache (run `manage.py createcachetable`).
if os.getenv('REDIS_URL'):
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': os.environ['REDIS_URL']}}
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'marketkura_cache'}}
