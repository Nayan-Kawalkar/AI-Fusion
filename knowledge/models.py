from django.db import models


class Document(models.Model):
    title = models.CharField(max_length=300)
    file = models.FileField(upload_to="docs/")
    kind = models.CharField(max_length=10)  # pdf / txt
    pages = models.IntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    indexed = models.BooleanField(default=False)
    source_url = models.URLField(max_length=1000, blank=True, default="")  # set for docs fetched from the web

    class Meta:
        db_table = "documents"

    def __str__(self):
        return self.title


class Skill(models.Model):
    """A reusable instruction pack, triggered with /name.

    `docs` are knowledge-base title patterns (retrieval is limited to them),
    `urls` are web docs that get fetched into the knowledge base.
    """

    name = models.SlugField(max_length=60, unique=True)
    description = models.CharField(max_length=300, blank=True)
    instructions = models.TextField(blank=True)
    docs = models.JSONField(default=list, blank=True)
    urls = models.JSONField(default=list, blank=True)
    source = models.TextField()  # the original SKILL.md
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "skills"
        ordering = ["name"]

    def __str__(self):
        return f"/{self.name}"


class Chunk(models.Model):
    """A retrievable unit of text; mirrored in Chroma under `chroma_id`."""

    source_type = models.CharField(max_length=10)  # "doc" | "code"
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.CASCADE, related_name="chunks")
    project_file = models.ForeignKey(
        "projects.ProjectFile", null=True, blank=True, on_delete=models.CASCADE, related_name="chunks"
    )
    text = models.TextField()
    page = models.IntegerField(null=True, blank=True)
    heading = models.CharField(max_length=300, blank=True)
    start_line = models.IntegerField(null=True, blank=True)
    end_line = models.IntegerField(null=True, blank=True)
    chroma_id = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = "chunks"

    def source_label(self):
        if self.source_type == "doc":
            return f"{self.document.title} · p.{self.page}"
        return f"{self.project_file.path}:{self.start_line}-{self.end_line}"
