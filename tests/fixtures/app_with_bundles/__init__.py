"""Fixture package: exercises the ``bundles.py`` convention.

``Kernel("tests.fixtures.app_with_bundles")`` finds ``bundles.py``, reads its
``BUNDLES`` mapping, and activates every listed bundle whose flags match the
build environment (or ``"all"``).
"""

from __future__ import annotations

from typing_extensions import override

from xtr_dependency_injection.bundle import Bundle, as_bundle


@as_bundle("listed")
class ListedBundle(Bundle):
    """A tiny bundle listed by ``bundles.py`` to prove the convention."""

    booted: bool = False

    @override
    async def boot(self) -> None:
        type(self).booted = True
