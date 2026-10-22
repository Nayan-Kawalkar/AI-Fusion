"""Enable Postgres row-level security on every CodeLens table (no-op on SQLite).

Supabase exposes the public schema through its REST API; RLS with no policies
means only the secret key / direct DB connection can reach these tables.
"""
from django.db import migrations

TABLES = [
    "projects", "project_files", "documents", "chunks", "query_logs", "llm_cache",
    "django_migrations", "django_content_type",
]


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(f'ALTER TABLE IF EXISTS public."{table}" ENABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [
        ("assistant", "0001_initial"),
        ("projects", "0001_initial"),
        ("knowledge", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(enable_rls, migrations.RunPython.noop)]
