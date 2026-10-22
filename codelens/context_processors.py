import time
from pathlib import Path

from django.conf import settings

_STARTED = str(int(time.time()))


def asset_version(request):
    """Cache-busting token for static assets.

    In DEBUG it follows the newest file in static/, so JS/CSS edits show up on
    reload without restarting the server.
    """
    if settings.DEBUG:
        files = (p for d in settings.STATICFILES_DIRS for p in Path(d).rglob("*") if p.is_file())
        return {"asset_version": str(int(max((p.stat().st_mtime for p in files), default=0)))}
    return {"asset_version": _STARTED}


def app_info(request):
    """Model and database names for the IDE status bar."""
    if settings.OPENROUTER_API_KEY:
        # OpenRouter picks the first available model in the list, so name the provider.
        model = "OpenRouter" + (" + Gemini backup" if settings.GEMINI_API_KEY else "")
        title = " → ".join(settings.OPENROUTER_MODELS + ([settings.GEMINI_MODEL] if settings.GEMINI_API_KEY else []))
    else:
        model = title = settings.GEMINI_MODEL
    return {"app_info": {"model": model, "model_title": title,
                         "db": "Supabase" if settings.SUPABASE_DB_URL else "SQLite"}}
