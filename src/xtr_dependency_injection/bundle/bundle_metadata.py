"""What ``@as_bundle`` records about a bundle class."""

from __future__ import annotations

from dataclasses import dataclass, field

from .required_bundle import RequiredBundle

__all__ = ["BundleMetadata"]


@dataclass(frozen=True, slots=True)
class BundleMetadata:
    """A bundle's declaration, as ``@as_bundle`` and ``@required_bundle`` recorded it.

    Attributes:
        name: The name the bundle is known by everywhere.
        config: Its config type; ``NoConfig`` when it takes none.
        resources: Modules and packages scanned like the application's.
        required: The peer bundles it depends on, in decoration order.
    """

    name: str
    config: type[object]
    resources: tuple[str, ...] = ()
    required: tuple[RequiredBundle, ...] = field(default_factory=tuple)
