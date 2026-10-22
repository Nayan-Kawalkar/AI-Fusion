from django.db import models


class QueryLog(models.Model):
    """One retrieve → answer round trip. /api/answer only works for an existing row."""

    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL)
    selection = models.TextField()
    problem = models.TextField(blank=True)
    mode = models.CharField(max_length=20)
    retrieved = models.JSONField()
    grounded = models.BooleanField()
    answer = models.JSONField(null=True, blank=True)
    latency_ms = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "query_logs"


class Conversation(models.Model):
    """A chat thread about one project (or about the docs only)."""

    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_conversations"


class ChatMessage(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10)  # user | assistant
    content = models.TextField()
    query_log = models.ForeignKey(QueryLog, null=True, blank=True, on_delete=models.SET_NULL)
    answer = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_messages"
        ordering = ["id"]


class CacheEntry(models.Model):
    """Persistent LLM response cache keyed by sha256 of the full prompt."""

    key = models.CharField(max_length=64, unique=True)
    model = models.CharField(max_length=100)
    response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "llm_cache"
