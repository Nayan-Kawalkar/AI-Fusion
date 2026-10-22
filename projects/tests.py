import io
import shutil
import zipfile
from unittest import mock

from django.conf import settings
from django.test import TestCase

from assistant import chat
from assistant.models import ChatMessage, QueryLog
from projects.models import Project, ProjectFile
from projects.workspace import EditError, export_zip, save_file, scan_project
from rag import store

SERVICES = (
    "def order_total(items):\n"
    "    total = 0\n"
    "    for i in range(len(items) - 1):\n"
    "        total += items[i]\n"
    "    return total\n\n"
    "def add(x, cart=[]):\n"
    "    cart.append(x)\n"
    "    return cart\n"
)
FIXED = SERVICES.replace("for i in range(len(items) - 1):\n        total += items[i]", "for item in items:\n        total += item")


class WorkspaceTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.CHROMA_PATH, ignore_errors=True)

    def setUp(self):
        self.project = Project.objects.create(name="shop", indexed=True)
        # Test DB ids restart each run; drop vectors a previous run may have left behind.
        store.delete_collection(store.project_collection(self.project.id))
        ProjectFile.objects.create(project=self.project, path="orders/services.py", language="python",
                                   content=SERVICES, size=len(SERVICES))
        ProjectFile.objects.create(project=self.project, path="README.md", language="markdown", content="# Shop\n", size=7)

    def test_scan_covers_every_file(self):
        ov = scan_project(self.project)
        self.assertEqual(ov["files"], 2)
        self.assertEqual(ov["totals"]["warning"], 1)
        self.assertEqual(ov["problems"][0]["path"], "orders/services.py")
        self.assertEqual(ov["problems"][0]["code"], "MutableDefaultArgument")

    def test_save_reindexes_and_zip_has_changes(self):
        pf, previous = save_file(self.project, "orders/services.py", FIXED)
        self.assertEqual(previous, SERVICES)
        self.assertTrue(pf.chunks.exists())
        self.assertEqual(store.get_collection(store.project_collection(self.project.id)).count(), pf.chunks.count())
        names = zipfile.ZipFile(io.BytesIO(export_zip(self.project))).namelist()
        self.assertEqual(sorted(names), ["shop/README.md", "shop/orders/services.py"])
        content = zipfile.ZipFile(io.BytesIO(export_zip(self.project))).read("shop/orders/services.py").decode()
        self.assertIn("for item in items", content)

    def test_save_rejects_escaping_paths(self):
        with self.assertRaises(EditError):
            save_file(self.project, "../outside.py", "x = 1\n")

    def test_validate_edits(self):
        edits = chat.validate_edits([
            {"path": "orders/services.py", "content": FIXED, "summary": "fix loop"},
            {"path": "orders/services.py", "content": "dup"},                 # duplicate path
            {"path": "../evil.py", "content": "x"},                           # escapes project
            {"path": "README.md", "content": "# Shop\n"},                     # no-op
            {"path": "orders/helpers.py", "content": "```python\ndef f():\n    pass\n```"},
        ], self.project, hint_mode=False)
        self.assertEqual([(e["path"], e["action"]) for e in edits],
                         [("orders/services.py", "modify"), ("orders/helpers.py", "create")])
        self.assertEqual(edits[0]["original"], SERVICES)
        self.assertEqual(edits[1]["content"], "def f():\n    pass\n")
        self.assertEqual(chat.validate_edits([{"path": "a.py", "content": "x"}], self.project, hint_mode=True), [])

    def test_chat_answer_requires_retrieval_and_strips_bad_citations(self):
        record = {"kind": "chat", "mode": "beginner", "message": "fix the total", "history": [], "file_path": "",
                  "selection": "", "start_line": 1, "queries": [], "grounded": True, "top_score": 0.6,
                  "focus_files": ["orders/services.py"], "threshold": 0.3, "retrieval_ms": 1,
                  "context": [{"n": 1, "id": "doc_x", "source_type": "doc", "label": "loops · p.1", "heading": "", "text": "range"}]}
        log = QueryLog.objects.create(project=self.project, selection="", problem="fix", mode="chat/beginner",
                                      retrieved=record, grounded=True)
        conv = chat.Conversation.objects.create(project=self.project)
        ChatMessage.objects.create(conversation=conv, role="user", content="fix the total", query_log=log)
        raw = {"reply": "Off by one [1][7].", "edits": [{"path": "orders/services.py", "content": FIXED}],
               "general_notes": "Use sum() [1].", "used_citations": [1, 7]}
        with mock.patch.object(chat, "generate_json", return_value=(raw, False)) as gen:
            res = chat.run_chat_answer(log)
        self.assertIn("=== orders/services.py ===", gen.call_args[0][0])
        a = res["answer"]
        self.assertEqual(a["reply"], "Off by one [1].")
        self.assertEqual(a["general_notes"], "Use sum().")
        self.assertTrue(a["grounded"])
        self.assertEqual(len(a["edits"]), 1)
        self.assertEqual(conv.messages.filter(role="assistant").count(), 1)
