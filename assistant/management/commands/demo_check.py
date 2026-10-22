import time

from django.conf import settings
from django.core.management.base import BaseCommand

from assistant import demo
from assistant.llm import LLMError, _attempts


class Command(BaseCommand):
    help = "Pre-demo readiness check: is every demo request cached, and which models respond right now?"

    def add_arguments(self, parser):
        parser.add_argument("--no-ping", action="store_true", help="skip the live model check")

    def handle(self, *args, **opts):
        self.stdout.write("Demo requests (from demo_script.json):")
        ready = missing = 0
        created = []
        try:
            for label, kind, body in demo.items():
                r = demo.retrieve(kind, body)
                created.append(r["query_id"])
                if demo.is_cached(kind, r["query_id"]):
                    ready += 1
                    self.stdout.write(self.style.SUCCESS(f"  READY    {label}"))
                else:
                    missing += 1
                    self.stdout.write(self.style.WARNING(f"  NOT CACHED  {label}"))
        except demo.DemoError as e:
            self.stdout.write(self.style.ERROR(f"  {e}"))
        finally:
            demo.cleanup(created)

        if not opts["no_ping"]:
            self.stdout.write("\nModels (one tiny live request each):")
            for label, fn in _attempts():
                started = time.perf_counter()
                try:
                    _, model = fn('Reply with {"ok": true}', "Reply with JSON only.", True, 0.0)
                    self.stdout.write(self.style.SUCCESS(f"  OK       {label:<32} {time.perf_counter() - started:5.1f}s  ({model})"))
                except (LLMError, Exception) as e:
                    self.stdout.write(self.style.WARNING(f"  DOWN     {label:<32} {str(e)[:90]}"))

        self.stdout.write("")
        if missing:
            self.stdout.write(self.style.WARNING(
                f"{ready} ready, {missing} not cached. Run `python manage.py warm_cache` (and keep the demo project unchanged)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"All {ready} demo requests are cached — they will answer instantly even if every model is down."))
        self.stdout.write(f"Live questions: models race (hedge after {settings.LLM_HEDGE_AFTER:.0f}s), "
                          f"then a sources-only fallback after {settings.LLM_DEADLINE:.0f}s.")
