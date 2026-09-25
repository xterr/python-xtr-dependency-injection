"""What the builder holds: one definition per service key, and where each came from."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass
from typing import Literal, TypeAlias

from typing_extensions import override

__all__ = ["Definition", "Lifetime", "Origin", "ServiceKey"]

ServiceKey: TypeAlias = tuple[type, Hashable | None]
"""``(provided type, qualifier)`` — the identity wireup registers a service under."""

Lifetime: TypeAlias = Literal["singleton", "scoped", "transient"]
"""How long wireup keeps what a definition builds."""


@dataclass(frozen=True, slots=True)
class Origin:
    """Who contributed a definition: the kernel, a bundle, or the application.

    Attributes:
        kind: ``"kernel"``, ``"bundle"`` or ``"app"``.
        name: The bundle's name, or ``module:qualname`` of the application
            object.
        note: How it got there, when not directly — e.g.
            ``"via autoconfigure of app.x:Y"``.
    """

    kind: Literal["kernel", "bundle", "app"]
    name: str
    note: str | None = None

    @override
    def __str__(self) -> str:
        described = f"{self.kind} {self.name}"
        return described if self.note is None else f"{described} ({self.note})"


@dataclass(frozen=True, slots=True)
class Definition:
    """One service as the builder knows it, before it is compiled for wireup.

    Attributes:
        key: The type and qualifier it is provided under.
        provider: The class, factory function or instance that builds it.
        kind: How ``provider`` is registered: ``"class"``, ``"factory"``,
            ``"instance"``, or ``"declared"`` for an object already marked
            with wireup's ``@injectable``.
        lifetime: How long wireup keeps what it builds.
        origin: Who contributed it.
        priority: Its position among definitions of one origin group:
            higher comes first in ``Sequence[T]`` and ``Mapping``
            collections.
        reset_method: The method ``ServicesResetter`` calls on it, when it is
            resettable.
    """

    key: ServiceKey
    provider: object
    kind: Literal["class", "factory", "instance", "declared"]
    lifetime: Lifetime
    origin: Origin
    priority: int = 0
    reset_method: str | None = None
