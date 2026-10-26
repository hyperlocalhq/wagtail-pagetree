"""Minimal Django settings for running the wagtail-pagetree test suite."""

import importlib.util

HAS_LOCALIZE = importlib.util.find_spec("wagtail_localize") is not None

SECRET_KEY = "wagtail-pagetree-tests"
DEBUG = False
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "wagtail_pagetree",
    "tests.testapp",
    *(
        ["wagtail_localize", "wagtail_localize.locales"]
        if HAS_LOCALIZE
        else ["wagtail.locales"]
    ),
    "wagtail.users",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.admin",
    "wagtail",
    "taggit",
    "modelcluster",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "tests.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

USE_TZ = True
USE_I18N = True
LANGUAGE_CODE = "de"
LANGUAGES = [("de", "German"), ("en", "English")]

WAGTAIL_I18N_ENABLED = True
WAGTAIL_CONTENT_LANGUAGES = LANGUAGES
WAGTAIL_SITE_NAME = "wagtail-pagetree tests"
WAGTAILADMIN_BASE_URL = "http://testserver"

STATIC_URL = "/static/"
