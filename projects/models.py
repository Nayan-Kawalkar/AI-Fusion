from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    indexed = models.BooleanField(default=False)

    class Meta:
        db_table = "projects"

    def __str__(self):
        return self.name


class ProjectFile(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="files")
    path = models.CharField(max_length=500)
    language = models.CharField(max_length=40)
    content = models.TextField()
    size = models.IntegerField()

    class Meta:
        db_table = "project_files"
        unique_together = [("project", "path")]
        ordering = ["path"]

    def __str__(self):
        return self.path
