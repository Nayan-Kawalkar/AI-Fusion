import json

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from knowledge.models import Chunk

from .chat import run_chat_answer, run_chat_retrieval
from .llm import LLMError
from .models import QueryLog
from .services import PipelineError, run_answer, run_retrieval


def _json_body(request):
    try:
        body = json.loads(request.body or "{}")
        return body if isinstance(body, dict) else {}
    except json.JSONDecodeError:
        return None


@require_POST
def retrieve_view(request):
    """Step 1: retrieval results are returned before any LLM call."""
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    try:
        return JsonResponse(run_retrieval(body))
    except PipelineError as e:
        return JsonResponse({"error": str(e)}, status=400)


@require_POST
def answer_view(request):
    """Step 2: requires a query_id produced by /api/retrieve."""
    body = _json_body(request)
    query_id = (body or {}).get("query_id")
    if not isinstance(query_id, int):
        return JsonResponse({"error": "query_id from /api/retrieve is required."}, status=400)
    log = QueryLog.objects.filter(pk=query_id).first()
    if log is None:
        return JsonResponse({"error": "Unknown query_id. Call /api/retrieve first."}, status=404)
    try:
        return JsonResponse(run_answer(log))
    except LLMError as e:
        return JsonResponse({"error": str(e)}, status=502)


@require_POST
def chat_retrieve_view(request):
    """Chat step 1: retrieval over docs + whole project, returned before any LLM call."""
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    try:
        return JsonResponse(run_chat_retrieval(body))
    except PipelineError as e:
        return JsonResponse({"error": str(e)}, status=400)


@require_POST
def chat_answer_view(request):
    """Chat step 2: requires the query_id from /api/chat/retrieve."""
    query_id = (_json_body(request) or {}).get("query_id")
    log = QueryLog.objects.filter(pk=query_id).first() if isinstance(query_id, int) else None
    if log is None:
        return JsonResponse({"error": "query_id from /api/chat/retrieve is required."}, status=400)
    try:
        return JsonResponse(run_chat_answer(log))
    except PipelineError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except LLMError as e:
        return JsonResponse({"error": str(e)}, status=502)


@require_GET
def chunk_view(request, chroma_id):
    c = Chunk.objects.select_related("document", "project_file").filter(chroma_id=chroma_id).first()
    if c is None:
        return JsonResponse({"error": "Chunk not found."}, status=404)
    data = {"id": c.chroma_id, "source_type": c.source_type, "heading": c.heading, "text": c.text,
            "label": c.source_label()}
    if c.source_type == "doc":
        data.update(title=c.document.title, page=c.page)
    else:
        data.update(path=c.project_file.path, start_line=c.start_line, end_line=c.end_line,
                    project_id=c.project_file.project_id)
    return JsonResponse(data)
