"""The bundle list, where the kernel looks for it first."""

from __future__ import annotations

from tests.fixtures.app_with_config_bundles import ConfiguredBundle

BUNDLES = {ConfiguredBundle: {"all": True}}
