"""A unit of work is asked for a service after it exited."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["UnitOfWorkClosedError"]


class UnitOfWorkClosedError(DependencyInjectionError):
    """The unit of work a container or a bound call resolves from has exited.

    Its scoped services were released when it did, so handing one out — or
    building one nothing would ever release — is refused. Work that outlives
    the unit it was started in, a task it spawned, opens one of its own with
    ``unit_of_work(container, join=False)``.
    """

    def __init__(self) -> None:
        """Compose the message."""
        super().__init__(
            "this unit of work has exited; open one with unit_of_work(container, join=False)"
        )
