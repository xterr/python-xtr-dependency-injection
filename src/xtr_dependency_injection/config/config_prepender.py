"""Letting a bundle adjust another bundle's config before it is loaded.

Messenger adds a ``messenger`` channel to logging's config, for instance —
without importing logging when logging is not active. That is why a target
may be named rather than typed: naming an optional peer never imports it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast, final

from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.exception import ConfigProviderError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["ConfigPrepender", "Prepend"]

C = TypeVar("C")


@dataclass(frozen=True, slots=True)
class Prepend:
    """One recorded ``transform``: who asked, for which bundle, and what to apply."""

    source: str
    target: str | None
    fn: Callable[[object], object]
    description: str


@final
class ConfigPrepender:
    """What ``Bundle.prepend`` receives: a way to transform other bundles' configs.

    Transforms apply after the application's base provider and before its
    transforms, in bundle order — so they add to what the application chose,
    and the application still has the last word.
    """

    __slots__ = ("_active", "_prepends", "_source", "env")

    env: str

    def __init__(
        self, *, env: str, source: str, active: Mapping[str, type], prepends: list[Prepend]
    ) -> None:
        """Record transforms from bundle ``source`` into ``prepends``.

        Args:
            env: The environment being built.
            source: The bundle whose ``prepend`` receives this.
            active: Every active bundle's name and config type.
            prepends: Where transforms are recorded, in call order.
        """
        self.env = env
        self._source = source
        self._active = active
        self._prepends = prepends

    def has_bundle(self, name: str) -> bool:
        """Return whether the bundle ``name`` is active in this build."""
        return name in self._active

    def transform(self, target: str | type[C], fn: Callable[[C], C], /) -> None:
        """Transform the config of ``target`` — a bundle name or a config type — with ``fn``.

        A target that is not active is ignored, and reported as skipped.

        Raises:
            ConfigProviderError: If the target bundle takes no config.
        """
        name = target if isinstance(target, str) else self._owner_of(target)
        described = f"{getattr(fn, '__module__', '?')}:{getattr(fn, '__qualname__', repr(fn))}"
        if name is not None and self._active.get(name) is NoConfig:
            raise ConfigProviderError(
                f"prepend by bundle {self._source}", f"bundle {name!r} takes no config"
            )
        active_name = name if name in self._active else None
        self._prepends.append(
            Prepend(self._source, active_name, cast("Callable[[object], object]", fn), described)
        )

    def _owner_of(self, config_type: type) -> str | None:
        return next((name for name, owned in self._active.items() if owned is config_type), None)
