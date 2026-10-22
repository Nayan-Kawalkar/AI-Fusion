"""Upload pipeline for the documentation KB: extract → chunk → embed → store."""
import os
import uuid

from django.core.files import File
from django.db import transaction

from rag import bm25_cache, store
from rag.embeddings import embed

from ..models import Chunk, Document
from .chunk import chunk_pages
from .extract import extract

ALLOWED_KINDS = {".pdf": "pdf", ".txt": "txt", ".md": "txt"}


class IngestError(Exception):
    pass


def kind_for(filename):
    kind = ALLOWED_KINDS.get(os.path.splitext(filename)[1].lower())
    if not kind:
        raise IngestError("Only PDF, TXT and MD files are supported.")
    return kind


def ingest_file(fileobj, filename, title=None, source_url=""):
    """Store an uploaded file and index it into the `docs` collection."""
    kind = kind_for(filename)
    doc = Document(title=title or os.path.splitext(os.path.basename(filename))[0], kind=kind, source_url=source_url)
    doc.file.save(os.path.basename(filename), File(fileobj), save=True)
    try:
        index_document(doc)
    except Exception:
        delete_document(doc)
        raise
    return doc


def ingest_path(path, title=None):
    with open(path, "rb") as f:
        return ingest_file(f, os.path.basename(path), title)


def index_document(doc):
    try:
        pages = extract(doc.file.path, doc.kind)
    except Exception as e:
        raise IngestError(f"Could not read {doc.kind.upper()} file: {e}") from e
    pieces = chunk_pages(pages)
    if not pieces:
        raise IngestError("No text could be extracted from this file.")
    with transaction.atomic():
        doc.pages = len(pages)
        Chunk.objects.bulk_create(
            [
                Chunk(source_type="doc", document=doc, text=p["text"], page=p["page"],
                      heading=p["heading"][:300], chroma_id=f"doc_{uuid.uuid4().hex}")
                for p in pieces
            ]
        )
        rows = list(doc.chunks.order_by("id"))
        vectors = embed([f"{doc.title} — {r.heading}\n{r.text}" for r in rows])
        store.add_chunks(
            store.DOCS_COLLECTION,
            ids=[r.chroma_id for r in rows],
            embeddings=vectors,
            documents=[r.text for r in rows],
            metadatas=[
                {"source_type": "doc", "title": doc.title, "page": r.page, "heading": r.heading,
                 "chunk_db_id": r.id, "document_id": doc.id}
                for r in rows
            ],
        )
        doc.indexed = True
        doc.save(update_fields=["pages", "indexed"])
    bm25_cache.invalidate(store.DOCS_COLLECTION)
    return len(rows)


def delete_document(doc):
    store.delete_ids(store.DOCS_COLLECTION, list(doc.chunks.values_list("chroma_id", flat=True)))
    if doc.file:
        doc.file.delete(save=False)
    doc.delete()
    bm25_cache.invalidate(store.DOCS_COLLECTION)
