"""Prompt construction for explain/debug requests."""
from knowledge.services.skills import prompt_block

from .schema import SCHEMA_EXAMPLE

SYSTEM_PROMPT = """You are CodeLens, a programming tutor and debugging assistant.
Rules:
1. Use ONLY the numbered CONTEXT blocks for documentation-based claims and cite them inline as [n], where n is the block number.
2. If the context does not support a claim, put it in "general_notes" and never cite it. Never invent citation numbers. If the documentation blocks do not address the user's question, do not cite them and set "grounded" to false.
3. Line numbers refer to the original file; they are printed at the start of each code line. Use them in "issues".
4. You never execute code. Reason about it statically.
5. "fixed_code" must be a drop-in replacement for exactly the selected lines (same indentation, no line-number prefixes), or "" if nothing needs to change.
6. Respond with a single JSON object that matches the schema. No markdown fences, no extra keys."""

MODE_RULES = {
    "beginner": "Audience: a beginner. Use plain language, define jargon, keep sentences short.",
    "expert": "Audience: an experienced developer. Be concise and technical; skip the basics.",
    "hint": (
        "Hint-first mode: do NOT reveal the full solution. Put 2-4 progressive hints in \"hints\" "
        "(vaguest first), and leave \"fixed_code\" and \"fix_explanation\" empty."
    ),
}

TASKS = {
    "explain": "Explain what the selected code does, step by step. Mention any bugs or risks you notice in \"issues\".",
    "debug": "Debug the selected code: find the bugs, explain why each is wrong, and propose a fix.",
}


def number_context(doc_chunks, code_chunks):
    """Assign citation numbers [1]..[n]: documentation first, then project code."""
    return [dict(c, n=i) for i, c in enumerate(list(doc_chunks) + list(code_chunks), start=1)]


def citation_map(context):
    return [
        {"n": c["n"], "id": c["id"], "source_type": c["source_type"], "label": c["label"], "heading": c["heading"]}
        for c in context
    ]


def _numbered(code, start_line):
    lines = code.split("\n")
    width = len(str(start_line + len(lines) - 1))
    return "\n".join(f"{start_line + i:>{width}} | {line}" for i, line in enumerate(lines))


def build_prompt(r):
    """Build the user prompt from a stored retrieval record."""
    context = r["context"]
    grounded = r["grounded"]
    parts = [
        f"TASK: {TASKS.get(r['action'], TASKS['explain'])}",
        MODE_RULES.get(r["mode"], MODE_RULES["beginner"]),
        f"GROUNDED: {str(grounded).lower()}",
    ]
    if r.get("skill"):
        parts.append(prompt_block(r["skill"]))
    if not grounded:
        parts.append(
            "The documentation knowledge base does NOT cover this question. Do not cite documentation blocks. "
            "Put any general programming knowledge in \"general_notes\" only. You may still cite project code blocks."
        )
    if r["code"].strip():
        where = r.get("file_path") or "pasted code"
        end = r["start_line"] + len(r["code"].split("\n")) - 1
        parts.append(f"FILE: {where} (selected lines {r['start_line']}-{end})\nCODE:\n{_numbered(r['code'], r['start_line'])}")
    else:
        parts.append("CODE: (none — the user asked a question without selecting code; leave issues and fixed_code empty)")
    parts.append(f"PROBLEM DESCRIPTION: {r['problem'] or '(none given)'}")
    if r["findings"]:
        lines = [f"- line {f['line']} [{f['severity']}] {f['code']}: {f['message']}" for f in r["findings"]]
        parts.append("STATIC ANALYSIS FINDINGS (ast/pyflakes; the code was not run):\n" + "\n".join(lines))
    else:
        parts.append("STATIC ANALYSIS FINDINGS: none")

    blocks = []
    for c in context:
        kind = "documentation" if c["source_type"] == "doc" else "project code"
        heading = f" — {c['heading']}" if c["heading"] else ""
        blocks.append(f"[{c['n']}] ({kind}: {c['label']}{heading})\n{c['text']}")
    parts.append("CONTEXT:\n" + ("\n\n".join(blocks) if blocks else "(no context retrieved)"))
    parts.append("OUTPUT JSON SCHEMA:\n" + SCHEMA_EXAMPLE)
    return "\n\n".join(parts)
