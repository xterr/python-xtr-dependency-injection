"""Where a definition or a compiler pass came from — one spelling, shared.

The kernel turns a bundle name or a scanned object into an :class:`Origin`
in several steps — ``build``, ``load``, ``autoconfigure`` and the compiler-pass
collection all need it. Keeping these two helpers in their own module lets
those steps share one spelling without importing ``kernel.kernel``, which would
be a cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_dependency_injection.builder.definition import Origin
from xtr_dependency_injection.bundle import KERNEL_BUNDLE

if TYPE_CHECKING:
    from xtr_dependency_injection.scan.scanned_object import ScannedObject

__all__ = ["origin_of", "scanned_origin"]


def origin_of(bundle: str) -> Origin:
    """Return the :class:`Origin` of ``bundle`` — kernel for the core bundle, else a bundle."""
    return Origin("kernel", bundle) if bundle == KERNEL_BUNDLE else Origin("bundle", bundle)


def scanned_origin(scanned: ScannedObject) -> Origin:
    """Return the :class:`Origin` of a scanned compiler pass — its app or owning bundle."""
    if scanned.owner is None:
        return Origin("app", scanned.name)
    return Origin("bundle", scanned.owner, f"compiler pass {scanned.name}")
