"""tracing.py -- LangSmith tracing (observability) for the DHIL agents.

Spans are created with langsmith.trace. If the langsmith package or an API key is missing, or tracing is off,
every span does nothing, so the system works exactly the same without LangSmith.

Environment variables (the documented LangSmith ones): LANGSMITH_TRACING=true, LANGSMITH_API_KEY, LANGSMITH_PROJECT.
Call setup() before the first traced step, or set the variables before starting the program.
"""
import contextlib
import os

try:
    import langsmith as ls
except Exception:
    ls = None


def enabled():
    return (ls is not None and os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
            and bool(os.environ.get("LANGSMITH_API_KEY")))


def setup(api_key=None, project=None):
    """Turn tracing on when a key is available. Returns a status line."""
    if api_key:
        os.environ["LANGSMITH_API_KEY"] = api_key.strip()
    if project:
        os.environ["LANGSMITH_PROJECT"] = project.strip()
    if ls is not None and os.environ.get("LANGSMITH_API_KEY"):
        os.environ["LANGSMITH_TRACING"] = "true"
    return status()


def turn_off():
    os.environ["LANGSMITH_TRACING"] = "false"
    return status()


def status():
    if ls is None:
        return "OFF (the langsmith package is not installed)"
    if not os.environ.get("LANGSMITH_API_KEY"):
        return "OFF (no LANGSMITH_API_KEY)"
    if os.environ.get("LANGSMITH_TRACING", "").lower() != "true":
        return "OFF (tracing is switched off)"
    return f"ON (project: {os.environ.get('LANGSMITH_PROJECT', 'default')})"


def plain(d):
    """Plain Python values only, so traces serialise cleanly."""
    out = {}
    for k, v in (d or {}).items():
        if hasattr(v, "item"):
            try:
                v = v.item()
            except Exception:
                v = str(v)
        out[str(k)] = v if isinstance(v, (int, float, str, bool, type(None))) else str(v)
    return out


class Span:
    def __init__(self):
        self.outputs = {}

    def set(self, **kw):
        self.outputs.update(plain(kw))


def _has_parent():
    try:
        return ls.get_current_run_tree() is not None
    except Exception:
        try:
            from langsmith.run_helpers import get_current_run_tree
            return get_current_run_tree() is not None
        except Exception:
            return True


@contextlib.contextmanager
def span(name, run_type="chain", inputs=None, root=False):
    """A traced step. Child spans are only recorded inside another trace (root=False), so loose calls
    such as unit tests do not create stray traces."""
    sp = Span()
    if not enabled() or (not root and not _has_parent()):
        yield sp
        return
    try:
        cm = ls.trace(name, run_type, inputs=plain(inputs))
    except Exception:
        yield sp
        return
    with cm as rt:
        yield sp
        try:
            rt.end(outputs=sp.outputs)
        except Exception:
            pass


def flush():
    """Send pending traces now (they are also sent in the background)."""
    if ls is None:
        return
    try:
        from langsmith.run_trees import get_cached_client
        get_cached_client().flush()
    except Exception:
        try:
            ls.Client().flush()
        except Exception:
            pass
