"""Answers assembled WITHOUT the LLM, used only when every model failed or timed out.

They contain nothing invented: the retrieved passages (with their [n] citations),
related project code and static-analysis findings, clearly marked `offline`.
They are never cached or stored as the real answer, so Retry asks the models again.
"""
import re

SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def _gist(text, limit=220):
    """First sentence or two of a chunk, without its heading line or code."""
    text = re.sub(r"^## .*\n+", "", text.strip())
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = " ".join(line.strip() for line in text.splitlines() if line.strip() and not line.startswith("    "))
    if len(text) <= limit:
        return text
    cut = text[:limit]
    m = list(SENTENCE_END.finditer(cut))
    return (cut[: m[-1].start() + 1] if m else cut.rsplit(" ", 1)[0] + "…").strip()


def _source_lines(context, k_docs=3, k_code=3):
    docs = [c for c in context if c["source_type"] == "doc"][:k_docs]
    code = [c for c in context if c["source_type"] == "code"][:k_code]
    lines, used = [], []
    if docs:
        lines.append("Most relevant documentation:")
        for c in docs:
            lines.append(f"- **{c['heading'] or c['label']}** — {_gist(c['text'])} [{c['n']}]")
            used.append(c["n"])
    if code:
        lines.append("\nRelated code in your project:")
        for c in code:
            lines.append(f"- `{c['label']}` {c['heading']} [{c['n']}]")
            used.append(c["n"])
    return "\n".join(lines), used, any(c["source_type"] == "doc" for c in docs)


def notice(reason):
    return (f"The AI models didn't respond in time ({reason}). This is not an AI answer: it lists the sources "
            "CodeLens retrieved and the static-analysis findings. Press Retry to ask the models again.")


def selection_answer(r, reason):
    """Offline stand-in for an Explain/Debug answer."""
    body, used, has_docs = _source_lines(r["context"])
    findings = r.get("findings") or []
    issues = [{"line": f["line"], "severity": f["severity"], "title": f["code"], "reason": f["message"], "citations": []}
              for f in findings]
    summary = (f"Static analysis found {len(findings)} issue(s) in the selection." if findings
               else "Static analysis found no issues in the selection.")
    return {
        "summary": summary, "explanation": body or "No relevant sources were retrieved.", "issues": issues,
        "fixed_code": "", "fix_explanation": "", "hints": [], "general_notes": "",
        "used_citations": sorted(used), "retrieval_grounded": bool(r["grounded"]),
        "grounded": bool(r["grounded"]) and has_docs, "offline": True, "offline_reason": notice(reason),
    }


def chat_answer(r, reason):
    """Offline stand-in for a chat reply."""
    body, used, has_docs = _source_lines(r["context"])
    files = r.get("focus_files") or []
    if files:
        body += "\n\nFiles most related to your question: " + ", ".join(f"`{f}`" for f in files) + "."
    return {
        "reply": body or "No relevant sources were retrieved for this question.", "general_notes": "", "edits": [],
        "used_citations": sorted(used), "retrieval_grounded": bool(r["grounded"]),
        "grounded": bool(r["grounded"]) and has_docs, "offline": True, "offline_reason": notice(reason),
    }
