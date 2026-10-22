"""Django settings for CodeLens RAG. All secrets come from .env."""
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or ("dev-only-insecure-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "projects",
    "knowledge",
    "rag",
    "analysis",
    "assistant",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "codelens.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "codelens.context_processors.asset_version",
                "codelens.context_processors.app_info",
            ],
        },
    },
]

WSGI_APPLICATION = "codelens.wsgi.application"

def _postgres_from_url(url):
    """Django DATABASES entry from a postgresql:// URL (Supabase connection string)."""
    u = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": (u.path or "/postgres").lstrip("/") or "postgres",
        "USER": unquote(u.username or "postgres"),
        "PASSWORD": unquote(u.password or ""),
        "HOST": u.hostname,
        "PORT": u.port or 5432,
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": "require", "connect_timeout": 15},
    }


# Supabase Postgres when SUPABASE_DB_URL is set; otherwise a local SQLite file.
# `manage.py test` always uses SQLite so tests never touch the real database.
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
SUPABASE_DB_URL = "" if TESTING else os.getenv("SUPABASE_DB_URL", "").strip()
DATABASES = {
    "default": _postgres_from_url(SUPABASE_DB_URL)
    if SUPABASE_DB_URL
    else {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uploads: a project may be up to 20 MB spread over many files.
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 5000
DATA_UPLOAD_MAX_NUMBER_FIELDS = 12000

# CodeLens configuration
CHROMA_PATH = BASE_DIR / ("chroma_test" if TESTING else "chroma_data")
LLM_CACHE_DIR = BASE_DIR / "llm_cache"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
# OpenRouter is tried first (models in order, routed by OpenRouter); Gemini is the backup.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODELS = [m.strip() for m in os.getenv(
    "OPENROUTER_MODELS",
    "google/gemma-4-31b-it:free,nvidia/nemotron-3-super-120b-a12b:free,minimax/minimax-m3.1-flash:free",
).split(",") if m.strip()]
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Reliability: a slow model is overtaken by the next one after LLM_HEDGE_AFTER seconds;
# after LLM_DEADLINE seconds the app falls back to a sources-only answer.
LLM_HEDGE_AFTER = float(os.getenv("LLM_HEDGE_AFTER", "12"))
LLM_DEADLINE = float(os.getenv("LLM_DEADLINE", "60"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash")  # used on 429/503
GROUNDING_THRESHOLD = float(os.getenv("GROUNDING_THRESHOLD", "0.30"))  # tuned by eval/run_eval.py
TOP_K = int(os.getenv("TOP_K", "6"))
TOP_K_CODE = int(os.getenv("TOP_K_CODE", "4"))

MAX_FILE_BYTES = 200 * 1024
MAX_PROJECT_BYTES = 20 * 1024 * 1024
