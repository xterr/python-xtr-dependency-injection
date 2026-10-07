"""How errors and reports name a provider — one spelling everywhere."""

from __future__ import annotations

__all__ = ["qualified_name"]


def qualified_name(obj: object) -> str:
    """Return ``module:qualname`` for ``obj`` when both are strings, else ``repr``.

    This is how reports and errors name a provider — a function, class or the
    like — as opposed to
    :func:`~xtr_dependency_injection.exception._naming.type_name`, which names
    a type in a service key.
    """
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        return f"{module}:{qualname}"
    return repr(obj)
