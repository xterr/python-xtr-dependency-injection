"""Two bundles claim one name."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["DuplicateBundleError"]


class DuplicateBundleError(DependencyInjectionError):
    """Two bundles, or two entry points, claim one name.

    A name identifies a bundle everywhere — in ``requires``, in
    ``exclude_bundles``, in a config prepend — so it must mean one thing.
    """

    name: str
    first: str
    second: str

    def __init__(self, name: str, first: str, second: str) -> None:
        """Record the name and both claimants."""
        self.name = name
        self.first = first
        self.second = second
        super().__init__(f"bundle name {name!r} is claimed by both {first} and {second}")
