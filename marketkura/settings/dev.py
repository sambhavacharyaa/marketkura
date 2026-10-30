"""Local development settings for MarketKuraa."""

import os

from django.core.management.utils import get_random_secret_key

from .base import *  # noqa: F403,F401


DEBUG = True
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY') or get_random_secret_key()
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',  # noqa: F405
    }
}

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
