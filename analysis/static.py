# SAFETY: this module NEVER executes user code. It only parses source text with
# ast.parse and pyflakes (which itself only builds an AST). Do not add exec, eval,
# compile-and-run, subprocess, or importing of user files here — ever.
"""Static findings for Python source: syntax errors, pyflakes, and a few AST checks."""
import ast

from pyflakes import api as pyflakes_api

ERROR_CODES = {
    "UndefinedName", "UndefinedLocal", "UndefinedExport", "DuplicateArgument", "ReturnOutsideFunction",
    "YieldOutsideFunction", "ContinueOutsideLoop", "BreakOutsideLoop", "DefaultExceptNotLast",
    "TwoStarredExpressions", "TooManyExpressionsInStarredAssignment",
}
MUTABLE_CALLS = {"list", "dict", "set", "defaultdict", "OrderedDict"}


class _Collector:
    """pyflakes reporter that collects findings instead of printing them."""

    def __init__(self):
        self.findings = []

    def unexpectedError(self, filename, msg):
        self.findings.append(_finding(1, 0, "error", "ParseError", str(msg)))

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.findings.append(_finding(lineno or 1, offset or 0, "error", "SyntaxError", msg))

    def flake(self, message):
        code = type(message).__name__
        severity = "error" if code in ERROR_CODES else "warning"
        text = message.message % message.message_args
        self.findings.append(_finding(message.lineno, getattr(message, "col", 0), severity, code, text))


def _finding(line, col, severity, code, message):
    return {"line": int(line), "col": int(col or 0), "severity": severity, "code": code, "message": message}


def _is_len_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len"
            and len(node.args) == 1)


def _ast_checks(tree):
    """Extra pattern checks pyflakes does not cover."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                mutable = isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                    isinstance(default, ast.Call) and isinstance(default.func, ast.Name)
                    and default.func.id in MUTABLE_CALLS
                )
                if mutable:
                    out.append(_finding(default.lineno, default.col_offset, "warning", "MutableDefaultArgument",
                                        "mutable default argument is shared between calls; use None instead"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range":
            for arg in node.args[-1:] if len(node.args) <= 2 else node.args[1:2]:
                if (isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add) and _is_len_call(arg.left)
                        and isinstance(arg.right, ast.Constant) and arg.right.value == 1):
                    out.append(_finding(node.lineno, node.col_offset, "warning", "PossibleOffByOne",
                                        "range(len(x) + 1) goes one past the last valid index"))
        elif isinstance(node, ast.Subscript) and _is_len_call(node.slice):
            target, inner = node.value, node.slice.args[0]
            if isinstance(target, ast.Name) and isinstance(inner, ast.Name) and target.id == inner.id:
                out.append(_finding(node.lineno, node.col_offset, "error", "IndexOutOfRange",
                                    f"{target.id}[len({target.id})] is always out of range"))
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            out.append(_finding(node.lineno, node.col_offset, "info", "BareExcept",
                                "bare 'except:' also catches KeyboardInterrupt and SystemExit"))
    return out


def analyze(source, filename="input.py"):
    """Return findings [{line, col, severity, code, message}] sorted by line."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return [_finding(e.lineno or 1, e.offset or 0, "error", "SyntaxError", e.msg)]
    except ValueError as e:  # e.g. null bytes
        return [_finding(1, 0, "error", "ParseError", str(e))]
    collector = _Collector()
    pyflakes_api.check(source, filename, reporter=collector)
    findings = collector.findings + _ast_checks(tree)
    unique = {(f["line"], f["code"], f["message"]): f for f in findings}
    return sorted(unique.values(), key=lambda f: (f["line"], f["col"]))


def analyze_for_language(source, language, filename="input.py"):
    return analyze(source, filename) if language == "python" else []
