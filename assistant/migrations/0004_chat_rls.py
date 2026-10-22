"""Row-level security for the chat tables (no-op on SQLite)."""
from django.db import migrations


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in ("chat_conversations", "chat_messages"):
        schema_editor.execute(f'ALTER TABLE IF EXISTS public."{table}" ENABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [("assistant", "0003_chat")]

    operations = [migrations.RunPython(enable_rls, migrations.RunPython.noop)]
