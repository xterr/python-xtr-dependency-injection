"""Choosing which of several services of one type a parameter receives."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import final

__all__ = ["Target"]


@final
@dataclass(frozen=True, slots=True)
class Target:
    """Point a container-provided parameter at a specific qualifier.

    Names the qualifier the container should resolve for this parameter, when
    several services of one type live under different qualifiers::

        def __init__(self, mailer: Annotated[Mailer, Target("smtp")]) -> None: ...

    On its own it marks the parameter as container-provided — no ``Autowire()``
    needed beside it, though ``Annotated[T, Autowire(), Target("smtp")]`` means the
    same. It cannot sit beside ``Autowire(param=...)`` or ``Autowire(env=...)``: a
    parameter is a parameter, an environment variable, or a qualified service.

    Attributes:
        name: The qualifier of the service to inject.
    """

    name: Hashable
