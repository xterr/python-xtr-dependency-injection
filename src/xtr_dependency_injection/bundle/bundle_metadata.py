"""What ``@as_bundle`` records about a bundle class."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["BundleMetadata"]


@dataclass(frozen=True, slots=True)
class BundleMetadata:
    """A bundle's declaration, as ``@as_bundle`` recorded it.

    Attributes:
        name: The name the bundle is known by everywhere.
        config: Its config type; ``NoConfig`` when it takes none.
        requires: Bundles that must be active with it.
        optional: Bundles it is ordered after when they are active; never
            pulled in.
        envs: The environments it is active in; ``None`` for every one.
        resources: Modules and packages scanned like the application's.
    """

    name: str
    config: type[object]
    requires: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    envs: tuple[str, ...] | None = None
    resources: tuple[str, ...] = ()
