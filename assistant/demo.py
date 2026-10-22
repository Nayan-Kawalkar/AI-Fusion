"""Demo-script helpers shared by `warm_cache` and `demo_check`.

Each item in demo_script.json is turned into the exact request the UI sends,
so its prompt — and therefore its cache key — matches what judges will trigger.
"""
import json

from django.conf import settings

from knowledge.models import Chunk
from projects.models import Project

from .chat import CHAT_SYSTEM, build_chat_prompt, run_chat_answer, run_chat_retrieval
from .llm import _cache_get, cache_key
from .models import Conversation, QueryLog
from .prompts import SYSTEM_PROMPT, build_prompt
from .services import run_answer, run_retrieval


class DemoError(Exception):
    pass


def load_script():
    path = settings.BASE_DIR / "demo_script.json"
    if not path.exists():
        raise DemoError("demo_script.json not found in the project root.")
    return json.loads(path.read_text(encoding="utf-8"))


def items(mode="beginner"):
    """Yield (label, kind, body) for every demo request."""
    script = load_script()
    project = Project.objects.filter(name=script.get("project", "demo_project")).order_by("-id").first()
    for it in script.get("selection", []):
        if project is None:
            raise DemoError("Demo project not found. Run `python manage.py load_demo` first.")
        chunk = Chunk.objects.filter(project_file__project=project, project_file__path=it["path"],
                                     heading=it["function"]).first()
        if chunk is None:
            raise DemoError(f"{it['function']} not found in {it['path']}.")
        yield (f"{it['action']:<7} {it['path']}:{chunk.start_line}-{chunk.end_line}", "selection", {
            "project_id": project.id, "file_path": it["path"], "code": chunk.text, "start_line": chunk.start_line,
            "problem_text": it.get("problem", ""), "action": it["action"], "mode": it.get("mode", mode), "language": "python",
        })
    for it in script.get("chat", []):
        yield (f"chat    {it['message'][:60]}", "chat", {
            "project_id": project.id if project else None, "message": it["message"], "mode": it.get("mode", mode),
            "file_path": it.get("file", ""), "selection": "", "start_line": 1,
        })
    for it in script.get("paste", []):
        yield (f"paste   {(it.get('problem') or it['code'])[:60]!r}", "selection", {
            "code": it["code"], "full_code": it["code"], "problem_text": it.get("problem", ""),
            "action": it.get("action", "debug"), "mode": it.get("mode", mode), "language": it.get("language", "python"),
        })


def retrieve(kind, body):
    return (run_chat_retrieval if kind == "chat" else run_retrieval)(body)


def is_cached(kind, query_id):
    log = QueryLog.objects.get(pk=query_id)
    if kind == "chat":
        key = cache_key(build_chat_prompt(log.retrieved, log.project), CHAT_SYSTEM, True)
    else:
        key = cache_key(build_prompt(log.retrieved), SYSTEM_PROMPT, True)
    return _cache_get(key) is not None


def answer(kind, query_id):
    log = QueryLog.objects.get(pk=query_id)
    return (run_chat_answer if kind == "chat" else run_answer)(log)


def cleanup(query_ids):
    """Remove the bookkeeping rows a warm-up/check created (cache entries stay)."""
    Conversation.objects.filter(messages__query_log_id__in=query_ids).delete()
    QueryLog.objects.filter(pk__in=query_ids).delete()
