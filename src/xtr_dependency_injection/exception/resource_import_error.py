"""A module the kernel scans failed to import."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["ResourceImportError"]


class ResourceImportError(DependencyInjectionError):
    """A scanned module failed to import; the original error is its ``__cause__``."""

    module: str

    def __init__(self, module: str) -> None:
        """Record the module that failed."""
        self.module = module
        super().__init__(f"cannot import scanned module {module!r}")
