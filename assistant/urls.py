from django.urls import path

from . import views

urlpatterns = [
    path("retrieve", views.retrieve_view),
    path("answer", views.answer_view),
    path("chat/retrieve", views.chat_retrieve_view),
    path("chat/answer", views.chat_answer_view),
    path("chunk/<str:chroma_id>", views.chunk_view),
]
