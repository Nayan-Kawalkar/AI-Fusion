"""Retrieve → answer pipeline. Retrieval is stored first; answers need its query_id."""
import time

from django.conf import settings

from analysis.static import analyze_for_language
from knowledge.services.skills import SkillError, activate, snapshot
from projects.models import Project
from rag.grounding import grounding
from rag.query_builder import build_queries, referenced_names
from rag.retrieve import retrieve

from . import offline
from .llm import LLMError, generate_json
from .models import QueryLog
from .prompts import SYSTEM_PROMPT, build_prompt, citation_map, number_context
from .schema import validate_answer

ACTIONS = {"explain", "debug"}
MODES = {"beginner", "expert", "hint"}


class PipelineError(Exception):
    pass


def run_retrieval(body):
    """Static analysis + query building + hybrid retrieval + grounding; saves a QueryLog."""
    started = time.perf_counter()
    code = (body.get("code") or "").replace("\r\n", "\n")
    try:
        skill, problem, doc_ids, skill_meta = activate((body.get("problem_text") or "").strip())
    except SkillError as e:
        raise PipelineError(str(e)) from e
    if not code.strip() and not problem:
        raise PipelineError("Select some code or describe your problem first.")
    action = body.get("action") if body.get("action") in ACTIONS else "explain"
    mode = body.get("mode") if body.get("mode") in MODES else "beginner"
    start_line = max(int(body.get("start_line") or 1), 1)
    end_line = start_line + len(code.split("\n")) - 1

    project, file_path, language = None, body.get("file_path") or "", body.get("language") or "python"
    full_source = body.get("full_code") or code
    if body.get("project_id"):
        project = Project.objects.filter(pk=body["project_id"]).first()
        pf = project.files.filter(path=file_path).first() if project and file_path else None
        if pf:
            full_source, language = pf.content, pf.language
    if full_source is code:
        start_line, end_line = 1, len(code.split("\n"))

    all_findings = analyze_for_language(full_source, language, file_path or "input.py")
    findings = [f for f in all_findings if start_line <= f["line"] <= end_line]
    queries = build_queries(code, problem, findings)
    exclude = (file_path, start_line, end_line) if file_path else None
    doc_chunks, code_chunks = retrieve(
        queries, project.id if project and project.indexed else None, exclude=exclude,
        symbols=referenced_names(code), doc_ids=doc_ids,
    )
    grounded, top_score = grounding(doc_chunks)
    context = number_context(doc_chunks, code_chunks)
    latency = int((time.perf_counter() - started) * 1000)

    record = {
        "action": action, "mode": mode, "code": code, "start_line": start_line, "file_path": file_path,
        "language": language, "problem": problem, "queries": queries, "findings": findings,
        "context": context, "grounded": grounded, "top_score": top_score,
        "threshold": settings.GROUNDING_THRESHOLD, "retrieval_ms": latency, "skill": snapshot(skill),
    }
    log = QueryLog.objects.create(
        project=project, selection=code, problem=problem, mode=f"{action}/{mode}",
        retrieved=record, grounded=grounded,
    )
    n_docs = len(doc_chunks)
    return {
        "query_id": log.id, "queries": queries, "findings": findings,
        "doc_chunks": context[:n_docs], "code_chunks": context[n_docs:],
        "grounded": grounded, "top_score": top_score, "threshold": settings.GROUNDING_THRESHOLD,
        "citations": citation_map(context), "latency_ms": latency,
        "start_line": start_line, "end_line": end_line, "skill": skill_meta,
    }


def run_answer(log, use_cache=True):
    """Generate (or return the stored) answer for a prior retrieval."""
    if log.answer:
        return {"query_id": log.id, "answer": log.answer, "citations": citation_map(log.retrieved["context"]),
                "cached": True, "latency_ms": log.latency_ms}
    started = time.perf_counter()
    r = log.retrieved
    try:
        raw, cached = generate_json(build_prompt(r), SYSTEM_PROMPT, use_cache=use_cache)
    except LLMError as e:
        # Every model failed or timed out: answer from sources + static analysis (not stored).
        return {"query_id": log.id, "answer": offline.selection_answer(r, str(e)),
                "citations": citation_map(r["context"]), "cached": False,
                "latency_ms": int((time.perf_counter() - started) * 1000)}
    context = r["context"]
    answer = validate_answer(
        raw,
        valid_ids=[c["n"] for c in context],
        doc_ids=[c["n"] for c in context if c["source_type"] == "doc"],
        grounded=r["grounded"],
        hint_mode=r["mode"] == "hint",
    )
    log.answer = answer
    log.latency_ms = int((time.perf_counter() - started) * 1000)
    log.save(update_fields=["answer", "latency_ms"])
    return {"query_id": log.id, "answer": answer, "citations": citation_map(context), "cached": cached,
            "latency_ms": log.latency_ms}
