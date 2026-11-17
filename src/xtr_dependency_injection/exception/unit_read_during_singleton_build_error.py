"""Something per unit of work is read while a singleton is built."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["UnitReadDuringSingletonBuildError"]


class UnitReadDuringSingletonBuildError(DependencyInjectionError):
    """A singleton's factory read what belongs to one unit of work.

    A singleton is built once and kept by every unit after, so it would hold
    on to whichever unit — whichever request — happened to build it. Raised in
    a kernel built in debug mode only; read it where it is used instead, or
    make the service scoped.
    """

    read: str

    def __init__(self, read: str) -> None:
        """Record what was read."""
        self.read = read
        reason = (
            "a singleton would keep whichever unit built it"
            " — read it where it is used, or make the service scoped"
        )
        super().__init__(f"{read} was read while a singleton was being built; {reason}")
