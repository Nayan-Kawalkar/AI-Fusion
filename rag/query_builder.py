"""Turn a code selection + problem description into 2-4 search queries.

Identifiers are extracted with ast.parse (or regex when the selection does not
parse). The code is never executed.
"""
import ast
import re
import textwrap

MAX_QUERIES = 4
EXC_RE = re.compile(r"\b[A-Z]\w*(?:Error|Exception|Warning|DoesNotExist)\b")
TRACEBACK_RE = re.compile(r"^\s*([\w.]*(?:Error|Exception|Warning|DoesNotExist|Exit|Interrupt))\b\s*:?\s*(.*)$")
CALL_RE = re.compile(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(")
IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+)?import\s+([\w., ]+)", re.M)
NOISE_CALLS = {"print", "len", "str", "int", "float", "list", "dict", "set", "tuple", "isinstance", "super", "self"}


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        inner = _dotted(node.func)
        if inner:
            parts.append(inner + "()")
    return ".".join(reversed(parts))


def extract_identifiers(code):
    """Return (imports, calls, exceptions) found in the code text."""
    imports, calls, exceptions = [], [], []
    try:
        tree = ast.parse(textwrap.dedent(code))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports += [f"{node.module or ''}.{a.name}".lstrip(".") for a in node.names]
            elif isinstance(node, ast.Call):
                name = _dotted(node.func)
                if name:
                    calls.append(".".join(name.split(".")[-3:]))
            elif isinstance(node, ast.Name) and EXC_RE.fullmatch(node.id):
                exceptions.append(node.id)
            elif isinstance(node, ast.Attribute) and EXC_RE.fullmatch(node.attr):
                exceptions.append(node.attr)
    except (SyntaxError, ValueError):
        for mod, names in IMPORT_RE.findall(code):
            imports += [f"{mod}.{n.strip()}".lstrip(".") for n in names.split(",") if n.strip()]
        calls = CALL_RE.findall(code)
        exceptions = EXC_RE.findall(code)
    dedupe = lambda xs: list(dict.fromkeys(xs))
    calls = [c for c in dedupe(calls) if c.split(".")[-1] not in NOISE_CALLS or "." in c]
    return dedupe(imports), calls[:15], dedupe(exceptions)


def referenced_names(code):
    """Names the selection uses (classes, functions, methods) for symbol lookup."""
    names = set()
    try:
        tree = ast.parse(textwrap.dedent(code))
    except (SyntaxError, ValueError):
        return {m.split(".")[-1] for m in CALL_RE.findall(code)} - NOISE_CALLS
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names - NOISE_CALLS


def traceback_line(problem_text):
    """Last 'SomeError: message' line of a pasted traceback, if any."""
    for line in reversed((problem_text or "").strip().splitlines()):
        m = TRACEBACK_RE.match(line)
        if m:
            return line.strip()
    return ""


def build_queries(code, problem_text="", findings=()):
    """Produce 2-4 retrieval queries (problem, traceback, identifiers, findings, code)."""
    queries = []
    problem = (problem_text or "").strip()
    tb = traceback_line(problem)
    if problem:
        queries.append(problem[:500])
    if tb and tb != problem:
        queries.append(tb)
    imports, calls, exceptions = extract_identifiers(code or "")
    idents = " ".join(imports + calls + exceptions)
    if idents:
        queries.append(f"Python {idents}"[:500])
    if findings:
        queries.append("; ".join(dict.fromkeys(f["message"] for f in findings))[:500])
    if len(queries) < MAX_QUERIES and (code or "").strip():
        queries.append(textwrap.dedent(code).strip()[:1000])
    return list(dict.fromkeys(queries))[:MAX_QUERIES]
