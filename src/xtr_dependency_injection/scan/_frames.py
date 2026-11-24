"""Whose module body is running, read from the call stack.

The innermost module body on the stack belongs to the module whose code is
running: every frame nearer is the import system's, or a function that module
called.

Private to the package.
"""

from __future__ import annotations

import inspect

__all__ = ["running_module"]


def running_module() -> str | None:
    """Return the name of the module whose body is running, or ``None`` outside one."""
    frame = inspect.currentframe()
    while frame is not None and frame.f_code.co_name != "<module>":
        frame = frame.f_back
    if frame is None:
        return None
    name = frame.f_globals.get("__name__")
    return name if isinstance(name, str) else None
