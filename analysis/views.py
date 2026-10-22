import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from projects.models import ProjectFile

from .static import analyze_for_language


@require_POST
def analyze_view(request):
    """Static findings for posted code, or for a stored project file."""
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    code = body.get("code")
    language = body.get("language", "python")
    path = body.get("path") or "input.py"
    if code is None and body.get("project_id") and body.get("path"):
        pf = ProjectFile.objects.filter(project_id=body["project_id"], path=body["path"]).first()
        if pf is None:
            return JsonResponse({"error": "File not found."}, status=404)
        code, language = pf.content, pf.language
    return JsonResponse({"findings": analyze_for_language(code or "", language, path)})
