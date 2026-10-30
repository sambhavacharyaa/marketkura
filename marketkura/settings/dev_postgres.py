"""Development settings on PostgreSQL, for testing ranked full-text search locally.

    DB_NAME=marketkura DB_USER=postgres python manage.py test --settings=marketkura.settings.dev_postgres
"""

import os

from .dev import *  # noqa: F403,F401

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'marketkura'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}
