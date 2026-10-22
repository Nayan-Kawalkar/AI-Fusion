import time
from unittest import mock

from django.test import SimpleTestCase, override_settings

from assistant import llm
from assistant.schema import validate_answer


@override_settings(OPENROUTER_API_KEY="or-key", GEMINI_API_KEY="g-key", GEMINI_MODEL="g-main", GEMINI_FALLBACK_MODEL="g-backup",
                   LLM_HEDGE_AFTER=0.3, LLM_DEADLINE=3)
class ProviderRaceTests(SimpleTestCase):
    def test_openrouter_is_primary(self):
        with mock.patch.object(llm, "_call_openrouter", return_value=("hi", "openrouter:m")) as orc, \
                mock.patch.object(llm, "_call_gemini") as gem:
            self.assertEqual(llm._call("p", None, False, 0.2), ("hi", "openrouter:m"))
        orc.assert_called_once()
        gem.assert_not_called()

    def test_failure_hands_over_immediately(self):
        with mock.patch.object(llm, "_call_openrouter", side_effect=llm._Retryable("429")), \
                mock.patch.object(llm, "_call_gemini", return_value=("hi", "gemini:g-main")) as gem:
            started = time.monotonic()
            self.assertEqual(llm._call("p", None, False, 0.2), ("hi", "gemini:g-main"))
        self.assertLess(time.monotonic() - started, 0.25)  # didn't wait for the hedge delay
        self.assertEqual(gem.call_args[0][0], "g-main")

    def test_slow_model_is_overtaken(self):
        def slow(*a):
            time.sleep(2)
            return "late", "openrouter:slow"
        with mock.patch.object(llm, "_call_openrouter", side_effect=slow), \
                mock.patch.object(llm, "_call_gemini", return_value=("fast", "gemini:g-main")):
            started = time.monotonic()
            self.assertEqual(llm._call("p", None, False, 0.2), ("fast", "gemini:g-main"))
        self.assertLess(time.monotonic() - started, 1.0)

    def test_invalid_json_counts_as_failure(self):
        with mock.patch.object(llm, "_call_openrouter", return_value=("not json at all", "openrouter:m")), \
                mock.patch.object(llm, "_call_gemini", return_value=('{"ok": 1}', "gemini:g-main")):
            self.assertEqual(llm._call("p", None, True, 0.2)[1], "gemini:g-main")

    def test_deadline_is_hard(self):
        def hang(*a):
            time.sleep(5)
            return "x", "m"
        with mock.patch.object(llm, "_call_openrouter", side_effect=hang), \
                mock.patch.object(llm, "_call_gemini", side_effect=hang):
            started = time.monotonic()
            with self.assertRaises(llm.LLMError):
                llm._call("p", None, False, 0.2, deadline=1)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_error_when_every_provider_fails(self):
        with mock.patch.object(llm, "_call_openrouter", side_effect=llm.LLMError("bad key")), \
                mock.patch.object(llm, "_call_gemini", side_effect=llm._Retryable("503")):
            with self.assertRaises(llm.LLMError):
                llm._call("p", None, False, 0.2)


class OfflineFallbackTests(SimpleTestCase):
    def test_offline_answer_uses_only_retrieved_material(self):
        from assistant import offline

        r = {"grounded": True, "findings": [{"line": 13, "severity": "warning", "code": "MutableDefaultArgument",
                                             "message": "mutable default"}],
             "context": [{"n": 1, "source_type": "doc", "label": "lists · p.2", "heading": "Mutable default arguments",
                          "text": "## Mutable default arguments\n\nDefaults are evaluated once. More text here."},
                         {"n": 2, "source_type": "code", "label": "orders/views.py:30-35", "heading": "def add_item", "text": "x"}]}
        a = offline.selection_answer(r, "timeout")
        self.assertTrue(a["offline"])
        self.assertEqual(a["used_citations"], [1, 2])
        self.assertIn("Defaults are evaluated once.", a["explanation"])
        self.assertEqual(a["issues"][0]["line"], 13)
        self.assertEqual(a["fixed_code"], "")
        self.assertTrue(offline.chat_answer(r, "timeout")["offline"])

    def test_parse_json_tolerates_think_and_prose(self):
        self.assertEqual(llm._parse_json('<think>hmm</think>Sure! {"a": 1} hope that helps'), {"a": 1})


class ValidateAnswerTests(SimpleTestCase):
    raw = {
        "summary": "Off by one [1].",
        "explanation": "range stops early [1][9], see [2, 3].",
        "issues": [{"line": "8", "severity": "fatal", "title": "Bug", "reason": "skips last [1]", "citations": [1, 7]}],
        "fixed_code": "```python\nfor item in items:\n    pass\n```",
        "general_notes": "Also consider sum() [2].",
        "used_citations": [1, 42],
    }

    def test_strips_unknown_citations_and_coerces(self):
        a = validate_answer(self.raw, valid_ids=[1, 2, 3], doc_ids=[1, 2], grounded=True)
        self.assertEqual(a["explanation"], "range stops early [1], see [2][3].")
        self.assertEqual(a["issues"][0]["line"], 8)
        self.assertEqual(a["issues"][0]["severity"], "warning")
        self.assertEqual(a["issues"][0]["citations"], [1])
        self.assertEqual(a["fixed_code"], "for item in items:\n    pass")
        self.assertEqual(a["general_notes"], "Also consider sum().")
        self.assertEqual(a["used_citations"], [1, 2, 3])
        self.assertTrue(a["grounded"])

    def test_ungrounded_cannot_cite_docs(self):
        a = validate_answer(self.raw, valid_ids=[1, 2, 3], doc_ids=[1, 2], grounded=False)
        self.assertEqual(a["used_citations"], [3])
        self.assertFalse(a["grounded"])

    def test_grounded_requires_a_doc_citation(self):
        raw = {"summary": "Uses project code only [3]."}
        a = validate_answer(raw, valid_ids=[1, 2, 3], doc_ids=[1, 2], grounded=True)
        self.assertTrue(a["retrieval_grounded"])
        self.assertFalse(a["grounded"])

    def test_hint_mode_hides_fix(self):
        a = validate_answer(self.raw, valid_ids=[1], doc_ids=[1], grounded=True, hint_mode=True)
        self.assertEqual(a["fixed_code"], "")
