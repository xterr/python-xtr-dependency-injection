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

from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Final, cast

from .bundle import METADATA_ATTRIBUTE, AnyBundle, Bundle

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["BUNDLES_ENTRY_POINT_GROUP", "installed_bundles"]

BUNDLES_ENTRY_POINT_GROUP: Final = "xtr_dependency_injection.bundles"
"""The entry point group a distribution advertises its bundle under."""


def installed_bundles() -> tuple[type[AnyBundle], ...]:
    """Return every bundle class an installed distribution advertises, each once.

    Each advertised target is imported, so call this from a diagnostic, not
    from a build. A target that cannot be loaded — its package installed
    without the extra its bundle needs, a name its module does not define, a
    module that fails as it is imported — is not usable here, and one that is
    not a class decorated with ``@as_bundle`` is not a bundle: both are
    skipped rather than failing the diagnostic.
    """
    found: list[type[AnyBundle]] = []
    for entry in sorted(entry_points(group=BUNDLES_ENTRY_POINT_GROUP), key=lambda e: e.name):
        load: Callable[[], object] = entry.load
        try:
            advertised = load()
        except Exception:  # noqa: BLE001, S112 — another distribution's code; one broken entry must not hide the rest.
            continue
        if not (isinstance(advertised, type) and issubclass(advertised, Bundle)):
            continue
        bundle_type = cast("type[AnyBundle]", advertised)
        if METADATA_ATTRIBUTE in vars(bundle_type) and bundle_type not in found:
            found.append(bundle_type)
    return tuple(found)
