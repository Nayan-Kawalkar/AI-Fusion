"""In-memory BM25 indexes per Chroma collection, built from Chunk rows."""
import re
import threading

from rank_bm25 import BM25Okapi

from knowledge.models import Chunk

from .store import DOCS_COLLECTION

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
CAMEL_RE = re.compile(r"_|(?<=[a-z0-9])(?=[A-Z])")
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "and", "or", "in", "on", "for",
    "with", "it", "this", "that", "my", "i", "me", "we", "you", "do", "does", "did", "why", "how",
    "what", "when", "can", "not", "but", "if", "as", "at", "by", "from", "so", "its", "have", "has",
}

_indexes = {}
_lock = threading.Lock()


def tokenize(text):
    """Lowercased tokens; identifiers also contribute their snake/camel parts."""
    tokens = []
    for word in TOKEN_RE.findall(text or ""):
        low = word.lower()
        if low in STOPWORDS:
            continue
        tokens.append(low)
        parts = [p.lower() for p in CAMEL_RE.split(word) if p]
        if len(parts) > 1:
            tokens.extend(p for p in parts if p not in STOPWORDS)
    return tokens


def _rows(collection):
    if collection == DOCS_COLLECTION:
        return Chunk.objects.filter(source_type="doc").values_list("chroma_id", "heading", "text")
    project_id = int(collection.split("_", 1)[1])
    return Chunk.objects.filter(source_type="code", project_file__project_id=project_id).values_list(
        "chroma_id", "heading", "text"
    )


def get_index(collection):
    """Return (BM25Okapi, ids) for a collection, building it on first use."""
    with _lock:
        if collection in _indexes:
            return _indexes[collection]
    rows = list(_rows(collection))
    ids = [r[0] for r in rows]
    corpus = [tokenize(f"{r[1]} {r[2]}") or ["_empty_"] for r in rows]
    entry = (BM25Okapi(corpus), ids) if rows else (None, [])
    with _lock:
        _indexes[collection] = entry
    return entry


def invalidate(collection=None):
    with _lock:
        if collection is None:
            _indexes.clear()
        else:
            _indexes.pop(collection, None)


def search(collection, query, k=10):
    """Top-k [(chroma_id, score)] with a positive BM25 score."""
    bm25, ids = get_index(collection)
    tokens = tokenize(query)
    if bm25 is None or not tokens:
        return []
    scores = bm25.get_scores(tokens)
    ranked = sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)[:k]
    return [(ids[i], float(scores[i])) for i in ranked if scores[i] > 0]
