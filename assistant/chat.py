"""Project chat: ask anything about the whole project, get grounded answers and optional file edits.

Same contract as Explain/Debug: `run_chat_retrieval` stores the retrieval first
(shown to the user), `run_chat_answer` needs its QueryLog. Edits are proposals
only; the user applies them. Project code is never executed.
"""
import re
import time

from django.conf import settings

from knowledge.services.skills import SkillError, activate, prompt_block, snapshot
from projects.models import Project
from projects.services import clean_path
from projects.workspace import project_map
from rag.grounding import grounding
from rag.query_builder import build_queries, referenced_names
from rag.retrieve import retrieve

from . import offline
from .llm import LLMError, generate_json
from .models import ChatMessage, Conversation, QueryLog
from .prompts import MODE_RULES, citation_map, number_context
from .schema import CITE_RE, FENCE_RE, clean_citations
from .services import PipelineError

HISTORY_TURNS = 6
FOCUS_FILES = 4
FOCUS_CHARS = 40_000
MAX_EDITS = 5
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

CHAT_SYSTEM = """You are CodeLens, an assistant that understands the user's whole project and their documentation.
Rules:
1. Use ONLY the numbered CONTEXT blocks for documentation-based claims and cite them inline as [n]. Never invent citation numbers.
2. Anything not supported by the context goes in "general_notes", without citations.
3. You never run code; reason about it statically. Refer to code as path:line.
4. Propose "edits" ONLY when the user asks you to fix, change, add, refactor or write something. Each edit holds the COMPLETE new file content (not a diff), keeps unrelated code exactly as it is, and uses a path from the PROJECT MAP (action "modify") or a new relative path (action "create"). At most 5 edits. Only modify files whose full content is shown under FILES.
5. Keep "reply" focused: explain the problem, the solution and where it lives. Use short paragraphs or bullet lists; wrap code in backticks.
6. Respond with a single JSON object matching the schema. No markdown fences around it."""

CHAT_SCHEMA = """{
  "reply": "markdown answer with inline [n] citations",
  "edits": [{"path": "orders/services.py", "action": "modify|create", "summary": "one line: what changes", "content": "COMPLETE new file content"}],
  "general_notes": "general knowledge not supported by the context, no citations",
  "grounded": true,
  "used_citations": [1, 2]
}"""


def _conversation(body, project):
    conv = None
    if body.get("conversation_id"):
        conv = Conversation.objects.filter(pk=body["conversation_id"], project=project).first()
    return conv or Conversation.objects.create(project=project)


def _focus_files(project, file_path, code_chunks):
    """Files whose full text goes into the prompt (so edits can be complete)."""
    paths = []
    for p in [file_path] + [c.get("path") for c in code_chunks]:
        if p and p not in paths:
            paths.append(p)
    focus, total = [], 0
    for pf in project.files.filter(path__in=paths[: FOCUS_FILES * 2]):
        if len(focus) >= FOCUS_FILES or total + len(pf.content) > FOCUS_CHARS:
            continue
        focus.append(pf.path)
        total += len(pf.content)
    return sorted(focus, key=paths.index)


def run_chat_retrieval(body):
    started = time.perf_counter()
    try:
        skill, message, doc_ids, skill_meta = activate((body.get("message") or "").strip())
    except SkillError as e:
        raise PipelineError(str(e)) from e
    if not message:
        raise PipelineError(f"Add a question after /{skill.name}." if skill else "Type a question first.")
    mode = body.get("mode") if body.get("mode") in MODE_RULES else "beginner"
    project = Project.objects.filter(pk=body.get("project_id")).first() if body.get("project_id") else None
    conv = _conversation(body, project)
    history = [
        {"role": m.role, "content": m.content[:2000]}
        for m in list(conv.messages.order_by("-id")[: HISTORY_TURNS])[::-1]
    ]
    selection = (body.get("selection") or "").replace("\r\n", "\n")
    file_path = body.get("file_path") or ""

    queries = build_queries(selection, message, [])
    # Short follow-ups ("fix it") need the previous question to retrieve well.
    last_user = next((h["content"] for h in reversed(history) if h["role"] == "user"), "")
    if last_user and len(message.split()) < 8:
        queries.insert(1, last_user[:500])
    queries = list(dict.fromkeys(queries))[:4]
    symbols = referenced_names(selection) | set(WORD_RE.findall(message))

    doc_chunks, code_chunks = retrieve(
        queries, project.id if project and project.indexed else None, symbols=symbols, k_code=6, doc_ids=doc_ids
    )
    grounded, top_score = grounding(doc_chunks)
    context = number_context(doc_chunks, code_chunks)
    focus = _focus_files(project, file_path, code_chunks) if project else []
    latency = int((time.perf_counter() - started) * 1000)

    record = {
        "kind": "chat", "mode": mode, "message": message, "history": history, "file_path": file_path,
        "selection": selection, "start_line": int(body.get("start_line") or 1), "queries": queries,
        "context": context, "grounded": grounded, "top_score": top_score, "focus_files": focus,
        "threshold": settings.GROUNDING_THRESHOLD, "retrieval_ms": latency, "skill": snapshot(skill),
    }
    log = QueryLog.objects.create(project=project, selection=selection, problem=message, mode=f"chat/{mode}",
                                  retrieved=record, grounded=grounded)
    ChatMessage.objects.create(conversation=conv, role="user", content=message, query_log=log)
    n_docs = len(doc_chunks)
    return {
        "query_id": log.id, "conversation_id": conv.id, "queries": queries,
        "doc_chunks": context[:n_docs], "code_chunks": context[n_docs:], "grounded": grounded,
        "top_score": top_score, "threshold": settings.GROUNDING_THRESHOLD, "citations": citation_map(context),
        "focus_files": focus, "latency_ms": latency, "skill": skill_meta,
    }


def build_chat_prompt(r, project):
    parts = [MODE_RULES.get(r["mode"], MODE_RULES["beginner"]), f"GROUNDED: {str(r['grounded']).lower()}"]
    if r.get("skill"):
        parts.append(prompt_block(r["skill"]))
    if not r["grounded"]:
        parts.append("The documentation knowledge base does not cover this question well. Do not cite documentation "
                     "blocks unless they truly apply; general knowledge goes in \"general_notes\". Project code may be cited.")
    if project:
        parts.append(f"PROJECT: {project.name}\nPROJECT MAP (every file; symbols and static-analysis counts):\n{project_map(project)}")
        files = {pf.path: pf.content for pf in project.files.filter(path__in=r["focus_files"])}
        if files:
            parts.append("FILES (complete current content; edit only these):\n" + "\n\n".join(
                f"=== {p} ===\n{files[p]}" for p in r["focus_files"] if p in files))
    if r["selection"].strip():
        parts.append(f"USER SELECTION in {r['file_path'] or 'pasted code'} starting at line {r['start_line']}:\n{r['selection']}")
    blocks = []
    for c in r["context"]:
        kind = "documentation" if c["source_type"] == "doc" else "project code"
        heading = f" — {c['heading']}" if c["heading"] else ""
        blocks.append(f"[{c['n']}] ({kind}: {c['label']}{heading})\n{c['text']}")
    parts.append("CONTEXT:\n" + ("\n\n".join(blocks) if blocks else "(nothing retrieved)"))
    if r["history"]:
        parts.append("CONVERSATION SO FAR:\n" + "\n".join(f"{h['role'].upper()}: {h['content']}" for h in r["history"]))
    parts.append(f"USER QUESTION: {r['message']}")
    parts.append("OUTPUT JSON SCHEMA:\n" + CHAT_SCHEMA)
    return "\n\n".join(parts)


def validate_edits(raw_edits, project, hint_mode):
    """Keep only safe, meaningful edits; attach the current content for diffing."""
    if hint_mode or not project:
        return []
    out, seen = [], set()
    for e in (raw_edits or [])[:MAX_EDITS]:
        if not isinstance(e, dict) or not isinstance(e.get("content"), str):
            continue
        path = clean_path(str(e.get("path") or ""))
        if not path or path in seen:
            continue
        content = e["content"]
        fence = FENCE_RE.match(content.strip())
        if fence:
            content = fence.group(1)
        if len(content.encode("utf-8")) > settings.MAX_FILE_BYTES:
            continue
        pf = project.files.filter(path=path).first()
        if pf and pf.content.rstrip("\n") == content.rstrip("\n"):
            continue  # no-op edit
        seen.add(path)
        out.append({
            "path": path, "action": "modify" if pf else "create",
            "summary": str(e.get("summary") or "").strip()[:300],
            "original": pf.content if pf else "", "content": content if content.endswith("\n") else content + "\n",
        })
    return out


def run_chat_answer(log, use_cache=True):
    r = log.retrieved
    if r.get("kind") != "chat":
        raise PipelineError("This query_id is not a chat retrieval.")
    msg = ChatMessage.objects.filter(query_log=log, role="user").select_related("conversation").first()
    if log.answer:
        return {"query_id": log.id, "answer": log.answer, "citations": citation_map(r["context"]), "cached": True,
                "latency_ms": log.latency_ms, "conversation_id": msg.conversation_id if msg else None}
    started = time.perf_counter()
    project = log.project
    try:
        raw, cached = generate_json(build_chat_prompt(r, project), CHAT_SYSTEM, use_cache=use_cache)
    except LLMError as e:
        # Every model failed or timed out: list the retrieved sources instead (not stored).
        return {"query_id": log.id, "answer": offline.chat_answer(r, str(e)), "citations": citation_map(r["context"]),
                "cached": False, "latency_ms": int((time.perf_counter() - started) * 1000),
                "conversation_id": msg.conversation_id if msg else None}

    context = r["context"]
    doc_ids = {c["n"] for c in context if c["source_type"] == "doc"}
    allowed = {c["n"] for c in context} if r["grounded"] else {c["n"] for c in context} - doc_ids
    used = set()
    answer = {
        "reply": clean_citations(str(raw.get("reply") or "").strip(), allowed, used),
        "general_notes": re.sub(r"\s+([.,;:])", r"\1", CITE_RE.sub("", str(raw.get("general_notes") or ""))).strip(),
        "edits": validate_edits(raw.get("edits"), project, r["mode"] == "hint"),
    }
    used.update(n for n in (raw.get("used_citations") or []) if isinstance(n, int) and n in allowed)
    answer["used_citations"] = sorted(used)
    answer["retrieval_grounded"] = bool(r["grounded"])
    answer["grounded"] = bool(r["grounded"]) and bool(used & doc_ids)

    log.answer = answer
    log.latency_ms = int((time.perf_counter() - started) * 1000)
    log.save(update_fields=["answer", "latency_ms"])
    if msg:
        ChatMessage.objects.create(conversation=msg.conversation, role="assistant",
                                   content=answer["reply"] or answer["general_notes"], query_log=log, answer=answer)
    return {"query_id": log.id, "answer": answer, "citations": citation_map(context), "cached": cached,
            "latency_ms": log.latency_ms, "conversation_id": msg.conversation_id if msg else None}
