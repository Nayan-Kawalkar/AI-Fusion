import os
import tempfile

from django.test import SimpleTestCase

from analysis.static import analyze


class StaticAnalysisTests(SimpleTestCase):
    def test_never_executes_code(self):
        target = os.path.join(tempfile.gettempdir(), "codelens_should_not_exist.txt")
        if os.path.exists(target):
            os.remove(target)
        analyze(f"open({target!r}, 'w').write('ran')\nraise SystemExit(1)\n")
        self.assertFalse(os.path.exists(target))

    def test_findings(self):
        src = (
            "import os\n"
            "def add(tag, tags=[]):\n"
            "    tags.append(tag)\n"
            "    return tagz\n"
            "for i in range(len(tags) + 1):\n"
            "    pass\n"
        )
        codes = {(f["line"], f["code"]) for f in analyze(src)}
        self.assertIn((1, "UnusedImport"), codes)
        self.assertIn((2, "MutableDefaultArgument"), codes)
        self.assertIn((4, "UndefinedName"), codes)
        self.assertIn((5, "PossibleOffByOne"), codes)

    def test_syntax_error(self):
        [f] = analyze("def broken(:\n    pass\n")
        self.assertEqual((f["code"], f["severity"], f["line"]), ("SyntaxError", "error", 1))
