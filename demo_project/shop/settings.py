"""Minimal settings for the demo shop."""
SECRET_KEY = "demo-only"
DEBUG = True
INSTALLED_APPS = ["django.contrib.contenttypes", "orders"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "shop.sqlite3"}}
ROOT_URLCONF = "shop.urls"
