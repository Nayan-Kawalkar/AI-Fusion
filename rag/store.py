"""Thin wrapper around a single persistent ChromaDB client (cosine space)."""
import threading

from django.conf import settings

DOCS_COLLECTION = "docs"

_client = None
_lock = threading.Lock()


def project_collection(project_id):
    return f"project_{project_id}"


def get_client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                import chromadb

                _client = chromadb.PersistentClient(
                    path=str(settings.CHROMA_PATH),
                    settings=chromadb.Settings(anonymized_telemetry=False),
                )
    return _client


def get_collection(name):
    """Get or create a collection; embeddings are always supplied by us."""
    return get_client().get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}, embedding_function=None
    )


def _clean_meta(meta):
    # Chroma rejects None values in metadata.
    return {k: v for k, v in meta.items() if v is not None}


def add_chunks(collection_name, ids, embeddings, documents, metadatas, batch=1000):
    col = get_collection(collection_name)
    for i in range(0, len(ids), batch):
        col.add(
            ids=ids[i : i + batch],
            embeddings=embeddings[i : i + batch],
            documents=documents[i : i + batch],
            metadatas=[_clean_meta(m) for m in metadatas[i : i + batch]],
        )


def query(collection_name, embedding, k=10, where=None):
    """Vector search (optionally metadata-filtered). Returns [{id, similarity, metadata, text}] best first."""
    col = get_collection(collection_name)
    n = col.count()
    if n == 0:
        return []
    res = col.query(
        query_embeddings=[embedding],
        n_results=min(k, n),
        where=where,
        include=["distances", "metadatas", "documents"],
    )
    out = []
    for cid, dist, meta, doc in zip(
        res["ids"][0], res["distances"][0], res["metadatas"][0], res["documents"][0]
    ):
        out.append({"id": cid, "similarity": 1.0 - float(dist), "metadata": meta or {}, "text": doc})
    return out


def get_embeddings(collection_name, ids):
    """Return {id: embedding} for the given ids."""
    if not ids:
        return {}
    res = get_collection(collection_name).get(ids=list(ids), include=["embeddings"])
    return {cid: list(emb) for cid, emb in zip(res["ids"], res["embeddings"])}


def delete_ids(collection_name, ids):
    if ids:
        get_collection(collection_name).delete(ids=list(ids))


def delete_collection(name):
    try:
        get_client().delete_collection(name)
    except Exception:
        pass  # collection did not exist


def delete_all_collections():
    for col in get_client().list_collections():
        delete_collection(getattr(col, "name", col))
