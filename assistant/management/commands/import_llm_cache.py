import json

from django.conf import settings
from django.core.management.base import BaseCommand

from assistant.models import CacheEntry


class Command(BaseCommand):
    help = "Load cached Gemini answers from a JSON export into the current database."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(settings.BASE_DIR / "supabase" / "llm_cache_export.json"))

    def handle(self, *args, **opts):
        with open(opts["path"], encoding="utf-8") as f:
            rows = json.load(f)
        added = 0
        for row in rows:
            _, created = CacheEntry.objects.update_or_create(
                key=row["key"], defaults={"model": row["model"], "response": row["response"]}
            )
            added += created
        self.stdout.write(f"{len(rows)} cache entries loaded ({added} new).")
