"""Fixture package: the bundle list beside the rest of the configuration.

``config/bundles.py`` lists :class:`ConfiguredBundle`; a ``bundles.py`` from an
earlier layout lists :class:`EarlierBundle` beside it, and is never read while
the first one is there.
"""

from __future__ import annotations

from xtr_dependency_injection.bundle import Bundle, as_bundle


@as_bundle("configured")
class ConfiguredBundle(Bundle):
    """Listed by ``config/bundles.py``."""


@as_bundle("earlier")
class EarlierBundle(Bundle):
    """Listed by the earlier ``bundles.py``."""
