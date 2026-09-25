"""A bundle something needs is not there."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["MissingBundleError"]


class MissingBundleError(DependencyInjectionError):
    """A bundle that is required, or listed explicitly, is absent or was skipped."""

    name: str
    required_by: str | None
    reason: str | None

    def __init__(self, name: str, required_by: str | None, reason: str | None) -> None:
        """Record the missing bundle, who needs it, and why it is missing, when known."""
        self.name = name
        self.required_by = required_by
        self.reason = reason
        needed = f"required by {required_by}" if required_by is not None else "listed explicitly"
        cause = f": {reason}" if reason is not None else ": it is not installed"
        super().__init__(f"bundle {name!r} ({needed}) is not available{cause}")
