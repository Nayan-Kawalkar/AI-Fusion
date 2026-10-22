"""Chunk project files into the `project_<id>` collection.

Python files are split with ast.parse (one chunk per top-level function, class
and method). The source is only parsed, never imported or executed.
"""
import ast
import uuid

from django.db import transaction

from knowledge.models import Chunk

from . import bm25_cache, store
from .embeddings import embed

WINDOW = 60
OVERLAP = 10
CLASS_FULL_MAX_LINES = 80


def line_windows(lines, first_line=1):
    """Fixed windows of WINDOW lines with OVERLAP lines of overlap."""
    out = []
    step = WINDOW - OVERLAP
    for i in range(0, max(len(lines), 1), step):
        part = lines[i : i + WINDOW]
        if "".join(part).strip():
            out.append(
                {"heading": "", "start_line": first_line + i, "end_line": first_line + i + len(part) - 1,
                 "text": "\n".join(part)}
            )
        if i + WINDOW >= len(lines):
            break
    return out


def _span(node):
    start = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
    return start, node.end_lineno


def _slice(lines, start, end):
    return "\n".join(lines[start - 1 : end])


def python_chunks(source):
    """AST chunks for a Python file. Raises SyntaxError if it does not parse."""
    tree = ast.parse(source)
    lines = source.splitlines()
    chunks, covered = [], set()
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)

    for node in tree.body:
        if isinstance(node, funcs):
            start, end = _span(node)
            chunks.append({"heading": f"def {node.name}", "start_line": start, "end_line": end,
                           "text": _slice(lines, start, end)})
            covered.update(range(start, end + 1))
        elif isinstance(node, ast.ClassDef):
            start, end = _span(node)
            covered.update(range(start, end + 1))
            methods = [n for n in node.body if isinstance(n, funcs)]
            full = end - start + 1 <= CLASS_FULL_MAX_LINES or not methods
            if full:
                text = _slice(lines, start, end)
                # Tiny methods (e.g. __str__) are already readable in the class chunk.
                methods = [m for m in methods if _span(m)[1] - _span(m)[0] >= 2]
            else:
                # Long class: header + fields, then just the method signatures.
                first_method = _span(methods[0])[0]
                sigs = [lines[m.lineno - 1].rstrip() + "  ..." for m in methods]
                text = _slice(lines, start, first_method - 1) + "\n" + "\n".join(sigs)
            chunks.append({"heading": f"class {node.name}", "start_line": start, "end_line": end, "text": text})
            for m in methods:
                m_start, m_end = _span(m)
                chunks.append({"heading": f"def {node.name}.{m.name}", "start_line": m_start, "end_line": m_end,
                               "text": _slice(lines, m_start, m_end)})

    # Module-level leftovers (imports, constants, script code) become one chunk.
    leftover = [i for i in range(1, len(lines) + 1) if i not in covered and lines[i - 1].strip()]
    if leftover:
        if leftover[-1] - leftover[0] + 1 > WINDOW * 2:
            for w in line_windows(lines):
                if any(w["start_line"] <= i <= w["end_line"] for i in leftover):
                    w["heading"] = "module code"
                    w["text"] = "\n".join(lines[i - 1] for i in range(w["start_line"], w["end_line"] + 1)
                                          if i not in covered)
                    chunks.append(w)
        else:
            chunks.append({"heading": "module code", "start_line": leftover[0], "end_line": leftover[-1],
                           "text": "\n".join(lines[i - 1] for i in leftover)})
    return chunks


def file_chunks(pf):
    """Chunks for one ProjectFile, falling back to line windows."""
    if pf.language == "python":
        try:
            return python_chunks(pf.content)
        except (SyntaxError, ValueError):
            pass  # still index broken files
    return line_windows(pf.content.splitlines())


def drop_file_chunks(pf):
    """Remove one file's chunks from SQLite/Postgres and Chroma."""
    collection = store.project_collection(pf.project_id)
    store.delete_ids(collection, list(pf.chunks.values_list("chroma_id", flat=True)))
    pf.chunks.all().delete()
    bm25_cache.invalidate(collection)


def reindex_file(pf):
    """Re-chunk and re-embed a single edited file."""
    drop_file_chunks(pf)
    rows = [
        Chunk(source_type="code", project_file=pf, text=c["text"], heading=c["heading"][:300],
              start_line=c["start_line"], end_line=c["end_line"], chroma_id=f"code_{uuid.uuid4().hex}")
        for c in file_chunks(pf)
    ]
    Chunk.objects.bulk_create(rows)
    rows = list(pf.chunks.order_by("id"))
    if rows:
        store.add_chunks(
            store.project_collection(pf.project_id),
            ids=[r.chroma_id for r in rows],
            embeddings=embed([f"{pf.path} :: {r.heading}\n{r.text}" for r in rows]),
            documents=[r.text for r in rows],
            metadatas=[
                {"source_type": "code", "path": pf.path, "heading": r.heading, "start_line": r.start_line,
                 "end_line": r.end_line, "chunk_db_id": r.id, "project_id": pf.project_id}
                for r in rows
            ],
        )
    bm25_cache.invalidate(store.project_collection(pf.project_id))
    return len(rows)


def index_project(project):
    """(Re)build the project's code chunks in SQLite and Chroma."""
    collection = store.project_collection(project.id)
    with transaction.atomic():
        Chunk.objects.filter(project_file__project=project).delete()
        store.delete_collection(collection)
        rows = []
        for pf in project.files.all():
            for c in file_chunks(pf):
                rows.append(
                    Chunk(source_type="code", project_file=pf, text=c["text"], heading=c["heading"][:300],
                          start_line=c["start_line"], end_line=c["end_line"],
                          chroma_id=f"code_{uuid.uuid4().hex}")
                )
        Chunk.objects.bulk_create(rows, batch_size=500)
        rows = list(
            Chunk.objects.filter(project_file__project=project).select_related("project_file").order_by("id")
        )
        if rows:
            vectors = embed([f"{r.project_file.path} :: {r.heading}\n{r.text}" for r in rows])
            store.add_chunks(
                collection,
                ids=[r.chroma_id for r in rows],
                embeddings=vectors,
                documents=[r.text for r in rows],
                metadatas=[
                    {"source_type": "code", "path": r.project_file.path, "heading": r.heading,
                     "start_line": r.start_line, "end_line": r.end_line, "chunk_db_id": r.id,
                     "project_id": project.id}
                    for r in rows
                ],
            )
        project.indexed = True
        project.save(update_fields=["indexed"])
    bm25_cache.invalidate(collection)
    return {"chunks": len(rows), "files": project.files.count()}
