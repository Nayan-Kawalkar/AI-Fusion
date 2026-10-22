"""Sentence-transformers embedding model, loaded once per process."""
import threading

from django.conf import settings

_model = None
_lock = threading.Lock()


def get_model():
    """Return the shared SentenceTransformer, loading it on first use."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")
    return _model


def embed(texts, batch_size=32):
    """Embed a list of strings into L2-normalised vectors (lists of floats)."""
    if not texts:
        return []
    vectors = get_model().encode(
        list(texts), batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
    )
    return vectors.tolist()


def embed_one(text):
    return embed([text])[0]
