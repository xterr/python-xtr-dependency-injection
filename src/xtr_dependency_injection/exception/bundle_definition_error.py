"""A bundle is declared in a way the kernel cannot use."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["BundleDefinitionError"]


class BundleDefinitionError(DependencyInjectionError):
    """A bundle is declared in a way the kernel cannot use.

    A bad ``@as_bundle``, a class missing it, a reserved name, a bundle or
    config type that cannot be built with no arguments, or two active bundles
    claiming one config type.
    """

    bundle: str
    reason: str

    def __init__(self, bundle: str, reason: str) -> None:
        """Record the bundle and what is wrong with it."""
        self.bundle = bundle
        self.reason = reason
        super().__init__(f"invalid bundle {bundle}: {reason}")
