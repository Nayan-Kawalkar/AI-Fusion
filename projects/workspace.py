"""Whole-project operations: static scan, project map for prompts, saving edits, zip export.

Like the rest of CodeLens, nothing here executes project code; files are only
parsed (ast/pyflakes via analysis.static) and stored as text.
"""
import io
import zipfile
from collections import Counter

from django.conf import settings
from django.db import transaction

from analysis.static import analyze_for_language
from knowledge.models import Chunk

from .models import ProjectFile
from .services import clean_path, detect_language

MAX_SCAN_FILES = 500
MAX_MAP_CHARS = 6000
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


class EditError(Exception):
    pass


def scan_project(project):
    """Static findings for every file plus size/language stats. No LLM involved."""
    files = list(project.files.only("path", "language", "content", "size")[:MAX_SCAN_FILES])
    languages = Counter()
    lines_total = 0
    per_file, problems = [], []
    for pf in files:
        lines = pf.content.count("\n") + 1 if pf.content else 0
        lines_total += lines
        languages[pf.language] += 1
        findings = analyze_for_language(pf.content, pf.language, pf.path)
        counts = Counter(f["severity"] for f in findings)
        per_file.append({"path": pf.path, "language": pf.language, "lines": lines,
                         "errors": counts["error"], "warnings": counts["warning"], "infos": counts["info"]})
        problems += [dict(f, path=pf.path) for f in findings]
    problems.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 3), f["path"], f["line"]))
    totals = Counter(f["severity"] for f in problems)
    return {
        "project_id": project.id, "name": project.name, "files": len(files), "lines": lines_total,
        "languages": languages.most_common(),
        "totals": {"error": totals["error"], "warning": totals["warning"], "info": totals["info"]},
        "per_file": per_file, "problems": problems[:300],
    }


def project_map(project):
    """Compact outline of the project (files, symbols, findings) for chat prompts."""
    symbols = {}
    for path, heading in Chunk.objects.filter(source_type="code", project_file__project=project) \
            .exclude(heading__in=["", "module code"]).values_list("project_file__path", "heading"):
        symbols.setdefault(path, []).append(heading)
    scan = {f["path"]: f for f in scan_project(project)["per_file"]}
    lines = []
    for pf in project.files.only("path", "language"):
        info = scan.get(pf.path, {})
        flags = []
        if info.get("errors"):
            flags.append(f"{info['errors']} errors")
        if info.get("warnings"):
            flags.append(f"{info['warnings']} warnings")
        syms = ", ".join(symbols.get(pf.path, [])[:12])
        lines.append(f"- {pf.path} ({info.get('lines', '?')} lines{'; ' + ', '.join(flags) if flags else ''})"
                     + (f": {syms}" if syms else ""))
    text = "\n".join(lines)
    return text if len(text) <= MAX_MAP_CHARS else text[:MAX_MAP_CHARS] + "\n- … (more files not shown)"


def validate_edit_path(project, path, must_exist):
    path = clean_path(path or "")
    if not path:
        raise EditError("Invalid file path.")
    exists = project.files.filter(path=path).exists()
    if must_exist and not exists:
        raise EditError(f"{path} does not exist in this project.")
    return path, exists


@transaction.atomic
def save_file(project, path, content):
    """Create or overwrite a file in the project copy and re-index it. Returns (pf, previous_content)."""
    from rag.code_indexer import reindex_file

    path, exists = validate_edit_path(project, path, must_exist=False)
    data = content.encode("utf-8")
    if len(data) > settings.MAX_FILE_BYTES:
        raise EditError(f"{path} would be larger than 200 KB.")
    pf = project.files.filter(path=path).first()
    previous = pf.content if pf else None
    if pf is None:
        pf = ProjectFile(project=project, path=path, language=detect_language(path))
    pf.content = content
    pf.size = len(data)
    pf.save()
    reindex_file(pf)
    return pf, previous


@transaction.atomic
def delete_file(project, path):
    """Remove a file from the project copy (used to undo an AI-created file)."""
    from rag.code_indexer import drop_file_chunks

    pf = project.files.filter(path=clean_path(path or "")).first()
    if pf is None:
        raise EditError("File not found.")
    drop_file_chunks(pf)
    pf.delete()


def export_zip(project):
    """Zip of the project's current files (including saved edits)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in project.files.values_list("path", "content"):
            zf.writestr(f"{project.name}/{path}", content)
    return buf.getvalue()
