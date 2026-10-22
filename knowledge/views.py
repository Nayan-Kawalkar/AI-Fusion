import json

from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import Document, Skill
from .services.ingest import IngestError, delete_document, ingest_file
from .services.skills import SkillError, install_skill, skill_info

MAX_DOC_BYTES = 50 * 1024 * 1024


def _doc_json(d):
    return {
        "id": d.id, "title": d.title, "kind": d.kind, "pages": d.pages, "indexed": d.indexed, "source_url": d.source_url,
        "chunks": getattr(d, "chunk_count", None), "uploaded_at": d.uploaded_at.isoformat(),
    }


@require_GET
def doc_list(request):
    docs = Document.objects.annotate(chunk_count=Count("chunks")).order_by("-uploaded_at")
    return JsonResponse({"docs": [_doc_json(d) for d in docs]})


@require_POST
def upload(request):
    files = request.FILES.getlist("file")
    if not files:
        return JsonResponse({"error": "No file received."}, status=400)
    created, errors = [], []
    for f in files:
        if f.size > MAX_DOC_BYTES:
            errors.append(f"{f.name}: larger than 50 MB")
            continue
        try:
            doc = ingest_file(f, f.name)
            doc.chunk_count = doc.chunks.count()
            created.append(_doc_json(doc))
        except IngestError as e:
            errors.append(f"{f.name}: {e}")
    status = 200 if created else 400
    return JsonResponse({"docs": created, "errors": errors, "error": "; ".join(errors) or None}, status=status)


def _skill_json(skill, url_results=None):
    url_docs = {d.source_url: d for d in Document.objects.filter(source_url__in=skill.urls).annotate(chunk_count=Count("chunks"))}
    info = skill_info(skill)
    return {
        "name": skill.name, "description": skill.description, "instructions": skill.instructions,
        "docs": skill.docs, "matched_docs": info["docs"], "scoped": info["scoped"],
        "urls": [{"url": u, "indexed": u in url_docs, "title": url_docs[u].title if u in url_docs else "",
                  "chunks": url_docs[u].chunk_count if u in url_docs else 0} for u in skill.urls],
        "url_results": url_results or [], "updated_at": skill.updated_at.isoformat(),
    }


@require_http_methods(["GET", "POST"])
def skills(request):
    """GET: list skills. POST: install/update from an uploaded SKILL.md (`file`) or `source` text."""
    if request.method == "GET":
        return JsonResponse({"skills": [_skill_json(s) for s in Skill.objects.all()]})
    upload = request.FILES.get("file")
    if upload is not None:
        if upload.size > 64 * 1024:
            return JsonResponse({"error": "Skill files must be under 64 KB."}, status=400)
        source = upload.read().decode("utf-8", errors="replace")
    else:
        try:
            source = json.loads(request.body or "{}").get("source", "")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON."}, status=400)
    try:
        skill, results = install_skill(source)
    except SkillError as e:
        return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"skill": _skill_json(skill, results)})


@require_http_methods(["GET", "DELETE"])
def skill_detail(request, name):
    skill = get_object_or_404(Skill, name=name)
    if request.method == "DELETE":
        skill.delete()  # fetched web docs stay in the knowledge base
        return JsonResponse({"deleted": name})
    return JsonResponse({"skill": _skill_json(skill), "source": skill.source})


@require_POST
def skill_refresh(request, name):
    """Re-fetch a skill's URLs (e.g. after the docs changed or a fetch failed)."""
    skill = get_object_or_404(Skill, name=name)
    for doc in Document.objects.filter(source_url__in=skill.urls):
        delete_document(doc)
    skill, results = install_skill(skill.source)
    return JsonResponse({"skill": _skill_json(skill, results)})


@require_http_methods(["DELETE"])
def delete(request, doc_id):
    delete_document(get_object_or_404(Document, pk=doc_id))
    return JsonResponse({"deleted": doc_id})
