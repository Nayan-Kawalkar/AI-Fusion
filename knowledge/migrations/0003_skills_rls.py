"""Row-level security for the skills table (no-op on SQLite)."""
from django.db import migrations


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute('ALTER TABLE IF EXISTS public."skills" ENABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0002_skills_and_web_docs")]

    operations = [migrations.RunPython(enable_rls, migrations.RunPython.noop)]
