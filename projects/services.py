"""Project upload handling: skip rules, size limits, text decoding, file tree."""
import fnmatch
import io
import os
import posixpath
import zipfile

from django.conf import settings
from django.db import transaction

from .models import Project, ProjectFile

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".tox", "site-packages", ".next",
}
BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip", ".gz", ".tar",
    ".7z", ".rar", ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".pyo", ".class", ".jar",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".avi", ".wav",
    ".sqlite3", ".db", ".pkl", ".npy", ".npz", ".h5", ".onnx", ".pt", ".docx", ".xlsx", ".pptx",
}
LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".html": "html", ".htm": "html", ".css": "css",
    ".scss": "scss", ".json": "json", ".md": "markdown", ".txt": "plaintext", ".yml": "yaml",
    ".yaml": "yaml", ".toml": "ini", ".ini": "ini", ".cfg": "ini", ".sql": "sql", ".sh": "shell",
    ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php", ".xml": "xml", ".kt": "kotlin",
}
MAX_ZIP_ENTRIES = 20000
IGNORE_FILE = ".codelensignore"


class UploadError(Exception):
    pass


def detect_language(path):
    return LANG_BY_EXT.get(posixpath.splitext(path)[1].lower(), "plaintext")


def clean_path(path):
    """Normalise to a relative POSIX path; None if it escapes the project root."""
    path = path.replace("\\", "/").lstrip("/")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def skip_reason(path, size):
    parts = path.split("/")
    if any(p in SKIP_DIRS or p.endswith(".egg-info") for p in parts[:-1]):
        return "skipped folder"
    if posixpath.splitext(path)[1].lower() in BINARY_EXTS:
        return "binary file"
    if size > settings.MAX_FILE_BYTES:
        return "larger than 200 KB"
    return None


def decode_text(data):
    """Return text, or None if the bytes look binary."""
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def strip_common_root(paths):
    """If every path shares one top-level folder, return (folder, stripped paths)."""
    tops = {p.split("/", 1)[0] for p in paths}
    if len(tops) == 1 and all("/" in p for p in paths):
        top = tops.pop()
        return top, [p.split("/", 1)[1] for p in paths]
    return None, paths


def entries_from_zip(fileobj):
    """Read accepted entries from a zip in memory; never extracts to disk."""
    try:
        zf = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile as e:
        raise UploadError("Not a valid .zip file.") from e
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_ZIP_ENTRIES:
        raise UploadError("Zip has too many files.")
    entries, skipped, total = [], [], 0
    for info in infos:
        path = clean_path(info.filename)
        if path is None:
            continue
        reason = skip_reason(path, info.file_size)
        if reason:
            skipped.append({"path": path, "reason": reason})
            continue
        total += info.file_size
        if total > settings.MAX_PROJECT_BYTES:
            raise UploadError("Project is larger than 20 MB after skip rules.")
        entries.append((path, zf.read(info)))
    return entries, skipped


def entries_from_dir(root):
    """Read accepted files from a local folder (used by `load_demo`)."""
    entries, skipped, total = [], [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            full = os.path.join(dirpath, filename)
            path = os.path.relpath(full, root).replace(os.sep, "/")
            size = os.path.getsize(full)
            reason = skip_reason(path, size)
            if reason:
                skipped.append({"path": path, "reason": reason})
                continue
            total += size
            if total > settings.MAX_PROJECT_BYTES:
                raise UploadError("Project is larger than 20 MB after skip rules.")
            with open(full, "rb") as f:
                entries.append((path, f.read()))
    return entries, skipped


def entries_from_files(files, paths):
    """Pair uploaded files with their webkitRelativePath values."""
    if len(paths) != len(files):
        paths = [f.name for f in files]
    entries, skipped, total = [], [], 0
    for f, raw_path in zip(files, paths):
        path = clean_path(raw_path)
        if path is None:
            continue
        reason = skip_reason(path, f.size)
        if reason:
            skipped.append({"path": path, "reason": reason})
            continue
        total += f.size
        if total > settings.MAX_PROJECT_BYTES:
            raise UploadError("Project is larger than 20 MB after skip rules.")
        entries.append((path, f.read()))
    return entries, skipped


def ignore_patterns(files):
    """Glob patterns from a root-level .codelensignore file (gitignore-lite)."""
    data = files.get(IGNORE_FILE)
    text = decode_text(data) if data else None
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def is_ignored(path, patterns):
    return path == IGNORE_FILE or any(
        fnmatch.fnmatch(path, p) or fnmatch.fnmatch(posixpath.basename(path), p) for p in patterns
    )


@transaction.atomic
def create_project(default_name, entries, skipped):
    """Create a Project + ProjectFiles from (path, bytes) entries."""
    root, stripped = strip_common_root([p for p, _ in entries])
    name = root or default_name or "project"
    patterns = ignore_patterns(dict(zip(stripped, (d for _, d in entries))))
    project = Project.objects.create(name=name)
    rows = []
    for path, (_, data) in zip(stripped, entries):
        if is_ignored(path, patterns):
            skipped.append({"path": path, "reason": ".codelensignore"})
            continue
        text = decode_text(data)
        if text is None:
            skipped.append({"path": path, "reason": "binary / not UTF-8"})
            continue
        rows.append(
            ProjectFile(project=project, path=path, language=detect_language(path), content=text, size=len(data))
        )
    if not rows:
        raise UploadError("No readable text files found in the upload.")
    ProjectFile.objects.bulk_create(rows)
    return project


def upload_project(request):
    """Handle POST /api/projects/upload for either a zip or a folder of files."""
    if "zip" in request.FILES:
        upload = request.FILES["zip"]
        if upload.size > settings.MAX_PROJECT_BYTES * 3:
            raise UploadError("Zip is too large.")
        entries, skipped = entries_from_zip(io.BytesIO(upload.read()))
        default_name = posixpath.splitext(upload.name)[0]
    else:
        files = request.FILES.getlist("files")
        if not files:
            raise UploadError("No files received.")
        entries, skipped = entries_from_files(files, request.POST.getlist("paths"))
        default_name = request.POST.get("name", "")
    project = create_project(default_name, entries, skipped)
    return project, skipped


def build_tree(project):
    """Nested {name, type, path, children} tree of the project's files."""
    root = {"name": project.name, "type": "dir", "path": "", "children": {}}
    for path, language in project.files.values_list("path", "language"):
        node = root
        parts = path.split("/")
        for i, part in enumerate(parts[:-1]):
            node = node["children"].setdefault(
                part, {"name": part, "type": "dir", "path": "/".join(parts[: i + 1]), "children": {}}
            )
        node["children"][parts[-1]] = {"name": parts[-1], "type": "file", "path": path, "language": language}

    def finish(node):
        if node["type"] == "dir":
            kids = sorted(node["children"].values(), key=lambda n: (n["type"] != "dir", n["name"].lower()))
            node["children"] = [finish(k) for k in kids]
        return node

    return finish(root)
