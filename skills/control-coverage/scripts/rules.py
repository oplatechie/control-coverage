"""Central code-structure rules (layer 3). Match what changed code does, using Python's ast.

Each rule looks at functions touched by the diff and returns the standards that apply,
with the changed lines inside that function as trigger lines.
"""
import ast
import os

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
SENSITIVE_NAMES = {"body", "payload", "request", "card_number", "pan", "card"}
DEPENDENCY_FILES = {"requirements.txt", "pyproject.toml", "poetry.lock", "package.json", "package-lock.json"}


def _names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | \
           {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def _call_name(call):
    f = call.func
    if isinstance(f, ast.Attribute):
        base = f.value.id if isinstance(f.value, ast.Name) else None
        return base, f.attr
    if isinstance(f, ast.Name):
        return None, f.id
    return None, None


def _functions(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def file_rules(path):
    """Rules that depend only on which file changed."""
    if os.path.basename(path) in DEPENDENCY_FILES:
        return [("dependency-file", "STD-SDLC-02")]
    return []


def scan(path, source, changed):
    """Return [(rule_id, standard_id, trigger_lines)] for one changed Python file."""
    if not path.endswith(".py") or source is None:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    changed = set(changed)
    hits = []
    for fn in _functions(tree):
        span = set(range(fn.lineno, (fn.end_lineno or fn.lineno) + 1))
        # decorator lines belong to the function too
        for d in fn.decorator_list:
            span |= set(range(d.lineno, (d.end_lineno or d.lineno) + 1))
        lines = sorted(span & changed)
        if not lines:
            continue

        # new or changed API endpoint
        for d in fn.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in HTTP_METHODS:
                for std in ("STD-AC-01", "STD-LOG-01", "STD-SDLC-01", "STD-DP-01"):
                    hits.append(("api-endpoint", std, lines))
                if "admin_required" in _names(fn.args):
                    hits.append(("admin-endpoint", "STD-AC-02", lines))

        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
            base, name = _call_name(call)
            # a login code or second factor delivered by email/SMS
            if name in {"send_email", "send_sms"} and ("auth" in path or "login" in fn.name):
                hits.append(("second-factor-delivery", "STD-AC-02", lines))
            # outbound HTTP
            if base in {"httpx", "requests"} and name in HTTP_METHODS | {"request"}:
                hits.append(("outbound-http", "STD-CRYPTO-01", lines))
            # logging request bodies or card fields
            if base in {"log", "logger", "logging"} and name in LOG_METHODS:
                if any(_names(a) & SENSITIVE_NAMES for a in call.args):
                    hits.append(("log-sensitive-data", "STD-CRYPTO-02", lines))
    return hits
