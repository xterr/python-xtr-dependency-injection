"""Where a definition or a compiler pass came from — one spelling, shared.

The kernel and the compiler passes turn a bundle name or a scanned object into
an :class:`Origin` in several places — preparing the container, loading
extensions, autoconfiguration, decorators and marked services all need it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_dependency_injection.bundle import KERNEL_BUNDLE

from .definition import Origin

if TYPE_CHECKING:
    from xtr_dependency_injection.scan.scanned_object import ScannedObject

__all__ = ["origin_of", "scanned_origin"]


def origin_of(bundle: str) -> Origin:
    """Return the :class:`Origin` of ``bundle`` — kernel for the core bundle, else a bundle."""
    return Origin("kernel", bundle) if bundle == KERNEL_BUNDLE else Origin("bundle", bundle)


def scanned_origin(scanned: ScannedObject, note: str) -> Origin:
    """Return the :class:`Origin` of a scanned object — the application, or its owning bundle.

    Args:
        scanned: What the scan found.
        note: How a bundle-owned object got there, e.g. ``"compiler pass"``;
            the object's name follows it.
    """
    if scanned.owner is None:
        return Origin("app", scanned.name)
    return Origin("bundle", scanned.owner, f"{note} {scanned.name}")
