"""Hybrid retrieval: Chroma vector search + BM25, fused with Reciprocal Rank Fusion."""
from collections import defaultdict

import numpy as np
from django.conf import settings
from django.db.models import Q

from knowledge.models import Chunk

from . import bm25_cache, store
from .embeddings import embed

RRF_K = 60
CANDIDATES = 10
CODE_MIN_SCORE = 0.3  # unrelated project code is noise in the inspector


def _chunk_json(chunk, score, rrf, via):
    base = {
        "id": chunk.chroma_id, "source_type": chunk.source_type, "heading": chunk.heading,
        "text": chunk.text, "score": round(score, 4), "rrf": round(rrf, 5), "via": sorted(via),
    }
    if chunk.source_type == "doc":
        base.update(title=chunk.document.title, page=chunk.page, label=f"{chunk.document.title} · p.{chunk.page}")
    else:
        path = chunk.project_file.path
        base.update(path=path, title=path, start_line=chunk.start_line, end_line=chunk.end_line,
                    label=f"{path}:{chunk.start_line}-{chunk.end_line}")
    return base


def symbol_chunk_ids(project_id, names):
    """Code chunks that define a name the selection references (class X / def X / def C.X)."""
    if not names:
        return []
    cond = Q()
    for n in list(names)[:40]:
        cond |= Q(heading=f"class {n}") | Q(heading=f"def {n}") | Q(heading__endswith=f".{n}")
    return list(
        Chunk.objects.filter(cond, source_type="code", project_file__project_id=project_id)
        .values_list("chroma_id", flat=True)[:8]
    )


def retrieve_collection(collection, queries, k, boost_ids=(), doc_ids=None):
    """Top-k fused results for several queries against one collection.

    `score` is the best cosine similarity of the chunk to any query (for display
    and grounding); ranking uses the RRF score. `boost_ids` (symbol matches) get
    the RRF credit of ranking first in two lists. `doc_ids` (from a skill)
    limits the docs collection to those documents.
    """
    queries = [q.strip() for q in queries if q and q.strip()]
    if not queries or doc_ids == []:
        return []
    q_vecs = embed(queries)
    fused = defaultdict(float)
    via = defaultdict(set)
    where, allowed = None, None
    if doc_ids is not None:
        where = {"document_id": {"$in": list(doc_ids)}}
        allowed = set(Chunk.objects.filter(document_id__in=doc_ids).values_list("chroma_id", flat=True))
    for cid in boost_ids:
        fused[cid] += 2.0 / (RRF_K + 1)
        via[cid].add("symbol")
    for query, vec in zip(queries, q_vecs):
        for rank, hit in enumerate(store.query(collection, vec, CANDIDATES, where=where)):
            fused[hit["id"]] += 1.0 / (RRF_K + rank + 1)
            via[hit["id"]].add("vector")
        bm25_hits = bm25_cache.search(collection, query, CANDIDATES if allowed is None else 200)
        if allowed is not None:
            bm25_hits = [h for h in bm25_hits if h[0] in allowed][:CANDIDATES]
        for rank, (cid, _) in enumerate(bm25_hits):
            fused[cid] += 1.0 / (RRF_K + rank + 1)
            via[cid].add("bm25")
    if not fused:
        return []

    ranked = sorted(fused, key=fused.get, reverse=True)
    chunks = {
        c.chroma_id: c
        for c in Chunk.objects.filter(chroma_id__in=ranked[: k * 3]).select_related("document", "project_file")
    }
    top_ids = [cid for cid in ranked if cid in chunks][:k]
    embeddings = store.get_embeddings(collection, top_ids)
    q_matrix = np.asarray(q_vecs)
    results = []
    for cid in top_ids:
        emb = embeddings.get(cid)
        cosine = float(np.max(q_matrix @ np.asarray(emb))) if emb is not None else 0.0
        results.append(_chunk_json(chunks[cid], cosine, fused[cid], via[cid]))
    return results


def _overlaps(chunk, path, start, end):
    return chunk.get("path") == path and chunk["start_line"] <= end and chunk["end_line"] >= start


def retrieve(queries, project_id=None, exclude=None, symbols=(), k_code=None, doc_ids=None):
    """Retrieve doc chunks (TOP_K) and, if a project is open, code chunks.

    `exclude=(path, start, end)` drops code chunks that overlap the user's own
    selection, so the inspector shows *related* code rather than the input.
    `symbols` are names used in the selection; their definitions are boosted.
    """
    doc_chunks = retrieve_collection(store.DOCS_COLLECTION, queries, settings.TOP_K, doc_ids=doc_ids)
    code_chunks = []
    k_code = k_code or settings.TOP_K_CODE
    if project_id:
        boost = symbol_chunk_ids(project_id, symbols)
        found = retrieve_collection(
            store.project_collection(project_id), queries, k_code + 4, boost_ids=boost
        )
        if exclude:
            found = [c for c in found if not _overlaps(c, *exclude)]
        code_chunks = [c for c in found if c["score"] >= CODE_MIN_SCORE or "symbol" in c["via"]]
        code_chunks = code_chunks[:k_code]
    return doc_chunks, code_chunks
