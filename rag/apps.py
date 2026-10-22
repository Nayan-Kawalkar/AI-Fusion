import os
import threading

from django.apps import AppConfig


class RagConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rag"

    def ready(self):
        # In the runserver worker process, load the embedding model and Chroma in
        # the background so the first Explain/Debug click is fast.
        if os.environ.get("RUN_MAIN") == "true":
            threading.Thread(target=_warm_up, daemon=True).start()


def _warm_up():
    from . import store
    from .embeddings import embed

    embed(["warm up"])
    store.get_client()
