import time

from django.core.management.base import BaseCommand, CommandError

from assistant import demo


class Command(BaseCommand):
    help = "Pre-answer every request in demo_script.json so the demo works instantly from cache."

    def add_arguments(self, parser):
        parser.add_argument("--mode", default="beginner", choices=["beginner", "expert", "hint"])
        parser.add_argument("--passes", type=int, default=2, help="re-try items that failed (rate limits)")

    def handle(self, *args, **opts):
        try:
            todo = list(demo.items(opts["mode"]))
        except demo.DemoError as e:
            raise CommandError(str(e))
        created = []
        for attempt in range(1, opts["passes"] + 1):
            failed = []
            for label, kind, body in todo:
                r = demo.retrieve(kind, body)
                created.append(r["query_id"])
                if demo.is_cached(kind, r["query_id"]):
                    self.stdout.write(f"  cached   {label}")
                    continue
                started = time.perf_counter()
                res = demo.answer(kind, r["query_id"])
                if res["answer"].get("offline"):
                    self.stdout.write(self.style.WARNING(f"  FAILED   {label}  ({res['answer']['offline_reason'][:90]}…)"))
                    failed.append((label, kind, body))
                else:
                    self.stdout.write(self.style.SUCCESS(f"  warmed   {label}  ({time.perf_counter() - started:.0f}s)"))
            if not failed or attempt == opts["passes"]:
                todo = failed
                break
            self.stdout.write(f"Retrying {len(failed)} failed item(s) in 20s…")
            time.sleep(20)
            todo = failed
        demo.cleanup(created)
        if todo:
            raise CommandError(f"{len(todo)} item(s) could not be warmed. Run warm_cache again later.")
        self.stdout.write(self.style.SUCCESS("All demo requests are cached. Run `python manage.py demo_check` to confirm."))
