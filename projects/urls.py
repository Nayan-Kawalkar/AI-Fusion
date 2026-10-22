from django.urls import path

from . import views

urlpatterns = [
    path("projects", views.project_list),
    path("projects/upload", views.upload),
    path("projects/<int:project_id>/index", views.index),
    path("projects/<int:project_id>/tree", views.tree),
    path("projects/<int:project_id>/file", views.file_content),
    path("projects/<int:project_id>/overview", views.overview),
    path("projects/<int:project_id>/download", views.download),
]
