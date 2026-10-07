"""The bundles installed distributions advertise — for diagnostics, never for activation.

A library advertises its bundle under the ``xtr_dependency_injection.bundles``
entry point group::

    [project.entry-points."xtr_dependency_injection.bundles"]
    mail = "acme_mail.bundle:MailBundle"

Advertising activates nothing: an application still lists the bundles it
wants. What it buys is a question the kernel's report cannot answer on its
own — *which installed bundles did the application leave out?* — so
``debug:bundles`` can point at a package that was added but never listed.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Final, cast

from .bundle import METADATA_ATTRIBUTE, AnyBundle, Bundle

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "BUNDLES_ENTRY_POINT_GROUP",
    "AdvertisedBundles",
    "advertised_bundles",
    "installed_bundles",
]

BUNDLES_ENTRY_POINT_GROUP: Final = "xtr_dependency_injection.bundles"
"""The entry point group a distribution advertises its bundle under."""


@dataclass(frozen=True, slots=True)
class AdvertisedBundles:
    """What the entry point group holds: the bundles it yields, and the entries that failed.

    Attributes:
        bundles: Every usable bundle class, each once, by entry point name.
        unusable: ``(entry point name, what it said)`` for each entry that
            could not be loaded — a package installed without the extra its
            bundle needs, a name its module does not define, a module that
            fails as it is imported. A diagnostic shows these rather than
            leaving the entry unaccounted for.
    """

    bundles: tuple[type[AnyBundle], ...]
    unusable: tuple[tuple[str, str], ...]


def installed_bundles() -> tuple[type[AnyBundle], ...]:
    """Return every bundle class an installed distribution advertises, each once.

    Each advertised target is imported, so call this from a diagnostic, not
    from a build. A target that cannot be loaded — its package installed
    without the extra its bundle needs, a name its module does not define, a
    module that fails as it is imported — is not usable here, and one that is
    not a class decorated with ``@as_bundle`` is not a bundle: both are
    skipped rather than failing the diagnostic. :func:`advertised_bundles`
    returns what the failed ones said.
    """
    return advertised_bundles().bundles


def advertised_bundles() -> AdvertisedBundles:
    """Return the advertised bundles, and what each entry that failed to load said.

    Loading an entry imports another distribution's module, so call this from
    a diagnostic, not from a build. A failure is reported, never raised: one
    broken entry must not hide the rest.
    """
    found: list[type[AnyBundle]] = []
    unusable: list[tuple[str, str]] = []
    for entry in sorted(entry_points(group=BUNDLES_ENTRY_POINT_GROUP), key=lambda e: e.name):
        load: Callable[[], object] = entry.load
        try:
            advertised = load()
        except Exception as error:  # noqa: BLE001 — another distribution's code; one broken entry must not hide the rest.
            unusable.append((entry.name, f"{type(error).__name__}: {error}"))
            continue
        if not (isinstance(advertised, type) and issubclass(advertised, Bundle)):
            continue
        bundle_type = cast("type[AnyBundle]", advertised)
        if METADATA_ATTRIBUTE in vars(bundle_type) and bundle_type not in found:
            found.append(bundle_type)
    return AdvertisedBundles(tuple(found), tuple(unusable))
