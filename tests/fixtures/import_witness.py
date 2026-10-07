"""A list the modules next to it append to as they are imported.

It lives apart from them so a test can read it without importing the module
whose import it witnesses — the only way to prove an import never happened.
"""

from __future__ import annotations

__all__ = ["WITNESSED"]

WITNESSED: list[str] = []
"""The name of every witnessed module imported so far, in import order."""
