from django.urls import path

from . import views

urlpatterns = [
    path("docs", views.doc_list),
    path("docs/upload", views.upload),
    path("docs/<int:doc_id>", views.delete),
    path("skills", views.skills),
    path("skills/<slug:name>", views.skill_detail),
    path("skills/<slug:name>/refresh", views.skill_refresh),
]
