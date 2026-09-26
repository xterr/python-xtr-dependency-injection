"""Ask, from a bundle hook, whether a peer bundle is active in this build.

A bundle that wires a peer only when it is present reads the ``kernel.bundles``
parameter — the mapping of active bundle name to ``module:Class`` the kernel
registers before any hook runs. :func:`bundle_active` is that read, spelled
once so every bundle does it the same way.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .container_builder import ContainerBuilder

__all__ = ["bundle_active"]


def bundle_active(builder: ContainerBuilder, name: str) -> bool:
    """Return whether the bundle ``name`` is active in the build ``builder`` sees.

    Reads the ``kernel.bundles`` parameter the kernel registers before any
    bundle hook runs. Usable from ``build`` onward, where that parameter
    exists; before then it is absent and this returns ``False``.
    """
    if not builder.has_parameter("kernel.bundles"):
        return False
    bundles = builder.get_parameter("kernel.bundles")
    return isinstance(bundles, Mapping) and name in bundles
