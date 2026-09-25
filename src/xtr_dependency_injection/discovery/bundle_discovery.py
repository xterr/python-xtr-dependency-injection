"""Finding installed bundles through entry points.

A package advertises its bundle under the ``xtr_dependency_injection.bundles``
group, keyed by the bundle's name::

    [project.entry-points."xtr_dependency_injection.bundles"]
    logging = "xtr_logging.bundle:LoggingBundle"

Installing the package is what registers it. Nothing is raised here: an entry
that cannot be used is reported as skipped, and becomes an error only when
something actually needs that bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Final, cast

from xtr_dependency_injection.bundle.bundle import METADATA_ATTRIBUTE, AnyBundle, Bundle
from xtr_dependency_injection.exception import DuplicateBundleError

__all__ = ["ENTRY_POINT_GROUP", "DiscoveredBundle", "discover_bundles"]

ENTRY_POINT_GROUP: Final = "xtr_dependency_injection.bundles"


@dataclass(frozen=True, slots=True)
class DiscoveredBundle:
    """One entry point of the bundles group, loaded or skipped.

    Attributes:
        name: The entry point's name — the bundle's name.
        value: Where it points, ``"module:Class"``.
        distribution: The distribution declaring it, when known.
        bundle: The bundle class; ``None`` when skipped.
        reason: Why it was skipped; ``None`` when loaded.
    """

    name: str
    value: str
    distribution: str | None
    bundle: type[AnyBundle] | None
    reason: str | None


def discover_bundles() -> tuple[DiscoveredBundle, ...]:
    """Return every bundle advertised by an installed distribution, sorted by name.

    One advertised twice — an editable install seen through two ``sys.path``
    entries — counts once.

    Raises:
        DuplicateBundleError: If one name points at two different classes.
    """
    chosen: dict[str, EntryPoint] = {}
    for entry in sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda e: (e.name, e.value)):
        existing = chosen.get(entry.name)
        if existing is None:
            chosen[entry.name] = entry
        elif existing.value != entry.value:
            raise DuplicateBundleError(entry.name, existing.value, entry.value)
    return tuple(_load(entry) for entry in chosen.values())


def _load(entry: EntryPoint) -> DiscoveredBundle:
    distribution = entry.dist.name if entry.dist is not None else None

    def skipped(reason: str) -> DiscoveredBundle:
        return DiscoveredBundle(entry.name, entry.value, distribution, None, reason)

    try:
        loaded = cast("object", entry.load())
    except ImportError as error:
        return skipped(f"cannot import {entry.value}: {error}")
    if not (isinstance(loaded, type) and issubclass(loaded, Bundle)):
        return skipped(f"{entry.value} is not a Bundle subclass")
    bundle = cast("type[AnyBundle]", loaded)
    if METADATA_ATTRIBUTE not in vars(bundle):
        return skipped(f"{entry.value} is not decorated with @as_bundle")
    declared = bundle.metadata().name
    if declared != entry.name:
        return skipped(f"{entry.value} declares the name {declared!r}, not {entry.name!r}")
    return DiscoveredBundle(entry.name, entry.value, distribution, bundle, None)
