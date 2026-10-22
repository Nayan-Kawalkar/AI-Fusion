from django.test import SimpleTestCase, TestCase

from knowledge.services.chunk import TARGET, chunk_pages
from knowledge.services.extract import split_pseudo_pages

PROSE = "Lists are ordered collections that you can change after creation. " * 12


def _fenced(n_lines):
    body = "\n".join(f"    value_{i} = compute({i})  # step {i}" for i in range(n_lines))
    return f"```python\ndef big_function():\n{body}\n```"


class ChunkerTests(SimpleTestCase):
    def test_fenced_code_block_is_never_split(self):
        # Prose fills most of a chunk so the boundary would land inside the code block.
        code = _fenced(60)  # ~2.5k chars, larger than what is left in the chunk
        text = f"# Section\n\n{PROSE}\n\n{PROSE}\n\n{code}\n\n{PROSE}"
        chunks = chunk_pages([(1, text)])
        holders = [c for c in chunks if "def big_function" in c["text"]]
        self.assertEqual(len(holders), 1)
        self.assertIn(code, holders[0]["text"])
        for c in chunks:
            self.assertEqual(c["text"].count("```") % 2, 0, "a chunk contains half a fenced block")

    def test_indented_code_block_kept_whole(self):
        code = "\n".join(f"    line_{i} = {i}" for i in range(150))
        text = f"{PROSE}\n\n{PROSE}\n\n{PROSE}\n\n{code}\n\n{PROSE}"
        chunks = chunk_pages([(1, text)])
        self.assertEqual(sum(code in c["text"] for c in chunks), 1)

    def test_heading_attached_and_size_bounded(self):
        text = "# Loops\n\n" + "\n\n".join([PROSE] * 8) + "\n\n## Ranges\n\nrange(stop) excludes stop."
        chunks = chunk_pages([(1, text)])
        self.assertTrue(all(c["heading"] for c in chunks))
        self.assertEqual(chunks[-1]["heading"], "Ranges")
        self.assertTrue(all(len(c["text"]) <= TARGET + 400 for c in chunks))

    def test_code_block_across_pseudo_pages(self):
        code = _fenced(150)
        pages = split_pseudo_pages(f"{PROSE}\n\n{code}\n\n{PROSE}", size=500)
        self.assertTrue(any(code in p for _, p in pages))


class SkillTests(SimpleTestCase):
    SOURCE = (
        "---\nname: django-backend\ndescription: Backend help\ndocs: [django_querysets, 'python_*']\n"
        "urls:\n  - https://docs.djangoproject.com/en/5.1/topics/db/queries/\n---\nKeep views thin.\n"
    )

    def test_parse_valid(self):
        from knowledge.services.skills import parse_skill

        s = parse_skill(self.SOURCE)
        self.assertEqual(s["name"], "django-backend")
        self.assertEqual(s["docs"], ["django_querysets", "python_*"])
        self.assertEqual(s["instructions"], "Keep views thin.")

    def test_parse_rejects_bad_files(self):
        from knowledge.services.skills import SkillError, parse_skill

        for bad in ["no front matter", "---\nname: Bad Name\n---\nx", "---\nname: ok-name\nurls: [ftp://x]\n---\n",
                    "---\nname: [unclosed\n---\n"]:
            with self.assertRaises(SkillError, msg=bad):
                parse_skill(bad)

    def test_private_urls_are_refused(self):
        from knowledge.services.web import FetchError, check_public_url

        for url in ["http://127.0.0.1:8000/admin", "http://localhost/", "http://10.0.0.5/", "file:///etc/passwd"]:
            with self.assertRaises(FetchError, msg=url):
                check_public_url(url)


class SkillScopeTests(TestCase):
    def setUp(self):
        from knowledge.models import Document, Skill

        for title in ["django_querysets", "python_loops", "python_errors", "react_hooks"]:
            Document.objects.create(title=title, kind="txt", file=f"docs/{title}.txt")
        Document.objects.create(title="web: Making queries", kind="txt", file="docs/w.txt",
                                source_url="https://docs.djangoproject.com/q/")
        Skill.objects.create(name="backend", docs=["django_*", "python_*"], urls=["https://docs.djangoproject.com/q/"],
                             source="x", instructions="Be concise.")
        Skill.objects.create(name="anything", source="x")

    def test_resolve_and_trigger(self):
        from knowledge.services.skills import SkillError, activate, parse_trigger, prompt_block, snapshot

        skill, rest, doc_ids, info = activate("/backend why is get() failing?")
        self.assertEqual((skill.name, rest), ("backend", "why is get() failing?"))
        self.assertEqual(sorted(info["docs"]), ["django_querysets", "python_errors", "python_loops", "web: Making queries"])
        self.assertIn("Be concise.", prompt_block(snapshot(skill)))
        self.assertIsNone(activate("/anything hi")[2])         # no docs/urls listed → search all docs
        self.assertEqual(parse_trigger("no slash here"), (None, "no slash here"))
        with self.assertRaises(SkillError):
            parse_trigger("/missing question")
