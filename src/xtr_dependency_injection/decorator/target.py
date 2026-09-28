"""Choosing which of several services of one type a parameter receives."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import final

from ._dependency_base import DependencyBase, set_dependency

__all__ = ["Target"]


@final
@dataclass(frozen=True, slots=True, init=False)
class Target(DependencyBase):
    """Point a container-provided parameter at a specific qualifier.

    Names the qualifier the container should resolve for this parameter, when
    several services of one type live under different qualifiers::

        def __init__(self, mailer: Annotated[Mailer, Target("smtp")]) -> None: ...

    On its own it marks the parameter as container-provided — no ``Autowire()``
    needed beside it, though ``Annotated[T, Autowire(), Target("smtp")]`` means the
    same. It cannot sit beside ``Autowire(param=...)`` or ``Autowire(env=...)``: a
    parameter is a parameter, an environment variable, or a qualified service.

    When the web framework is installed the marker is also one of its
    dependency declarations, so the same annotation resolves through the
    container inside a route; ``**fastapi`` exists for the framework's own
    copy of a marker and is never written by hand.

    Attributes:
        name: The qualifier of the service to inject.
    """

    name: Hashable

    def __init__(self, name: Hashable, **fastapi: object) -> None:
        """Record the qualifier the container resolves for this parameter."""
        object.__setattr__(self, "name", name)
        set_dependency(self, fastapi, qualifier=name)
