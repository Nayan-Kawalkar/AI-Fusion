from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView

urlpatterns = [
    path("", ensure_csrf_cookie(TemplateView.as_view(template_name="ide.html")), name="ide"),
    path(
        "knowledge/",
        ensure_csrf_cookie(TemplateView.as_view(template_name="knowledge.html")),
        name="knowledge",
    ),
    path("skills/", ensure_csrf_cookie(TemplateView.as_view(template_name="skills.html")), name="skills"),
    path("api/", include("projects.urls")),
    path("api/", include("knowledge.urls")),
    path("api/", include("analysis.urls")),
    path("api/", include("assistant.urls")),
]
