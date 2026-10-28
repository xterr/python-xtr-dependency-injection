"""A bundle list from an earlier layout, shadowed by ``config/bundles.py``."""

from __future__ import annotations

from tests.fixtures.app_with_config_bundles import EarlierBundle

BUNDLES = {EarlierBundle: {"all": True}}
