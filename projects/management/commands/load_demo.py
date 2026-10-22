import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from knowledge.models import Chunk, Document, Skill
from knowledge.services.ingest import delete_document, ingest_path
from knowledge.services.skills import install_skill, resolve_doc_ids
from projects.models import Project
from projects.services import create_project, entries_from_dir
from rag import bm25_cache, store
from rag.code_indexer import index_project


class Command(BaseCommand):
    help = "Wipe the KB + projects, then index demo_kb/ and demo_project/."

    def handle(self, *args, **options):
        started = time.perf_counter()
        for doc in Document.objects.all():
            delete_document(doc)
        Project.objects.all().delete()
        Skill.objects.all().delete()
        Chunk.objects.all().delete()
        store.delete_all_collections()
        bm25_cache.invalidate()
        self.stdout.write("Wiped existing documents, projects and Chroma collections.")

        kb_dir = settings.BASE_DIR / "demo_kb"
        for name in sorted(os.listdir(kb_dir)):
            if os.path.splitext(name)[1].lower() not in (".txt", ".md", ".pdf"):
                continue
            doc = ingest_path(kb_dir / name)
            self.stdout.write(f"  doc  {doc.title:<40} {doc.pages:>3} pages {doc.chunks.count():>4} chunks")

        skills_dir = settings.BASE_DIR / "demo_skills"
        for name in sorted(os.listdir(skills_dir)):
            if not name.endswith(".md"):
                continue
            skill, results = install_skill((skills_dir / name).read_text(encoding="utf-8"))
            failed = [r["url"] for r in results if not r["ok"]]
            self.stdout.write(f"  skill /{skill.name:<38} {len(resolve_doc_ids(skill) or []):>3} docs"
                              + (f"  (could not fetch: {', '.join(failed)})" if failed else ""))

        entries, skipped = entries_from_dir(settings.BASE_DIR / "demo_project")
        project = create_project("demo_project", entries, skipped)
        stats = index_project(project)
        self.stdout.write(
            f"  code {project.name:<40} {stats['files']:>3} files {stats['chunks']:>4} chunks"
            f" ({len(skipped)} skipped: {', '.join(s['path'] for s in skipped)})"
        )
        self.stdout.write(self.style.SUCCESS(
            f"Demo loaded in {time.perf_counter() - started:.1f}s — "
            f"{Document.objects.count()} documents, project id {project.id}."
        ))
