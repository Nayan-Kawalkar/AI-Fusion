import sys

from django.core.management.base import BaseCommand, CommandError

from assistant.llm import LLMError, _call


class Command(BaseCommand):
    help = "Send 'Say hello' to the configured LLM (OpenRouter, then Gemini) and print the reply. Bypasses the cache."

    def handle(self, *args, **options):
        try:
            text, model = _call("Say hello", None, False, 0.2)
        except LLMError as e:
            raise CommandError(str(e))
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe = text.strip().encode(encoding, "replace").decode(encoding)  # Windows consoles can't print emoji
        self.stdout.write(f"[{model}] {safe}")
