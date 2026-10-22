import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from rag.code_indexer import index_project

from .models import Project
from .services import UploadError, build_tree, upload_project
from .workspace import EditError, delete_file, export_zip, save_file, scan_project


@require_GET
def project_list(request):
    projects = Project.objects.order_by("-created_at")[:50]
    return JsonResponse(
        {
            "projects": [
                {"id": p.id, "name": p.name, "indexed": p.indexed, "files": p.files.count()}
                for p in projects
            ]
        }
    )


@require_POST
def upload(request):
    try:
        project, skipped = upload_project(request)
    except UploadError as e:
        return JsonResponse({"error": str(e)}, status=400)
    stats = index_project(project)
    return JsonResponse(
        {
            "project_id": project.id,
            "name": project.name,
            "file_count": project.files.count(),
            "skipped": skipped[:200],
            "skipped_count": len(skipped),
            "indexed": project.indexed,
            "chunks": stats["chunks"],
        }
    )


@require_POST
def index(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    stats = index_project(project)
    return JsonResponse({"project_id": project.id, "indexed": True, **stats})


@require_GET
def tree(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    return JsonResponse({"project_id": project.id, "name": project.name, "tree": build_tree(project)})


@require_http_methods(["GET", "POST", "DELETE"])
def file_content(request, project_id):
    """GET a file's text, POST {path, content} to save it, DELETE ?path= to remove it (project copy only)."""
    project = get_object_or_404(Project, pk=project_id)
    if request.method == "DELETE":
        try:
            delete_file(project, request.GET.get("path"))
        except EditError as e:
            return JsonResponse({"error": str(e)}, status=404)
        return JsonResponse({"deleted": request.GET.get("path")})
    if request.method == "POST":
        try:
            body = json.loads(request.body or "{}")
            pf, previous = save_file(project, body.get("path"), body.get("content") or "")
        except (json.JSONDecodeError, EditError) as e:
            return JsonResponse({"error": str(e) if isinstance(e, EditError) else "Invalid JSON."}, status=400)
        return JsonResponse({"path": pf.path, "language": pf.language, "size": pf.size, "created": previous is None})
    pf = project.files.filter(path=request.GET.get("path", "")).first()
    if pf is None:
        return JsonResponse({"error": "File not found."}, status=404)
    return JsonResponse({"path": pf.path, "language": pf.language, "content": pf.content, "size": pf.size})


@require_GET
def overview(request, project_id):
    """Static scan of the whole project (all files), no AI call."""
    return JsonResponse(scan_project(get_object_or_404(Project, pk=project_id)))


@require_GET
def download(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    response = HttpResponse(export_zip(project), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{project.name}.zip"'
    return response
