"""Answer JSON schema and validation of (untrusted) model output."""
import re

SEVERITIES = {"error", "warning", "info"}
CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
FENCE_RE = re.compile(r"^```[\w+-]*\n(.*?)\n?```\s*$", re.S)

SCHEMA_EXAMPLE = """{
  "summary": "one or two sentence overview",
  "explanation": "detailed explanation with inline [n] citations",
  "issues": [{"line": 12, "severity": "error|warning|info", "title": "short title", "reason": "why it is a problem, with [n] citations", "citations": [1]}],
  "fixed_code": "corrected replacement for the selected lines, or empty string",
  "fix_explanation": "what changed and why, with [n] citations",
  "hints": ["progressive hint"],
  "general_notes": "anything NOT supported by the context (general knowledge), no citations",
  "grounded": true,
  "used_citations": [1, 3]
}"""


def _str(value):
    return value.strip() if isinstance(value, str) else ""


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clean_citations(text, allowed, used):
    """Keep only [n] markers whose n is allowed; record the ones kept."""

    def repl(m):
        keep = []
        for part in m.group(1).split(","):
            n = int(part)
            if n in allowed:
                keep.append(n)
                used.add(n)
        return "".join(f"[{n}]" for n in keep)

    return re.sub(r"\s+([.,;:])", r"\1", CITE_RE.sub(repl, text)) if text else text


def validate_answer(raw, valid_ids, doc_ids, grounded, hint_mode=False):
    """Coerce model JSON into the schema; strip citations that don't exist.

    When the KB is not grounded, documentation blocks may not be cited at all.
    """
    raw = raw if isinstance(raw, dict) else {}
    allowed = set(valid_ids) if grounded else set(valid_ids) - set(doc_ids)
    used = set()

    issues = []
    for item in raw.get("issues") or []:
        if not isinstance(item, dict):
            continue
        cites = [n for n in (_int(c) for c in item.get("citations") or []) if n in allowed]
        used.update(cites)
        severity = _str(item.get("severity")).lower()
        issues.append({
            "line": _int(item.get("line")),
            "severity": severity if severity in SEVERITIES else "warning",
            "title": _str(item.get("title")) or "Issue",
            "reason": clean_citations(_str(item.get("reason")), allowed, used),
            "citations": cites,
        })

    fixed = _str(raw.get("fixed_code")) if isinstance(raw.get("fixed_code"), str) else ""
    fence = FENCE_RE.match(fixed)
    if fence:
        fixed = fence.group(1)
    if hint_mode:
        fixed = ""

    hints = [h.strip() for h in raw.get("hints") or [] if isinstance(h, str) and h.strip()]
    answer = {
        "summary": clean_citations(_str(raw.get("summary")), allowed, used),
        "explanation": clean_citations(_str(raw.get("explanation")), allowed, used),
        "issues": issues,
        "fixed_code": fixed.rstrip("\n"),
        "fix_explanation": clean_citations(_str(raw.get("fix_explanation")), allowed, used),
        "hints": hints,
        "general_notes": re.sub(r"\s+([.,;:])", r"\1", CITE_RE.sub("", _str(raw.get("general_notes")))).strip(),
    }
    used.update(n for n in (_int(c) for c in raw.get("used_citations") or []) if n in allowed)
    answer["used_citations"] = sorted(used)
    # Retrieval can match the *code* while the question is about something else,
    # so the final verdict also requires the answer to cite at least one doc.
    answer["retrieval_grounded"] = bool(grounded)
    answer["grounded"] = bool(grounded) and any(n in set(doc_ids) for n in used)
    return answer
