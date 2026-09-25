"""A compiled kernel was booted twice."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["KernelAlreadyBootedError"]


class KernelAlreadyBootedError(DependencyInjectionError):
    """``boot()`` was called a second time on one compiled kernel.

    Boot hooks run once per container; build the kernel again for another.
    """

    def __init__(self) -> None:
        """Compose the message."""
        super().__init__("this compiled kernel was already booted; build a new one")
