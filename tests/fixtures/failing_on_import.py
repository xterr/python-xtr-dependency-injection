"""A module that fails as it is imported, for a reason other than a missing module."""

from __future__ import annotations

__all__: list[str] = []

message = "this module cannot be imported"
raise RuntimeError(message)
