"""Declaring bundles: the base class, its decorator, and what the decorator records."""

from __future__ import annotations

from .as_bundle import as_bundle
from .bundle import KERNEL_BUNDLE, Bundle, NoConfig
from .bundle_metadata import BundleMetadata
from .installed_bundles import (
    BUNDLES_ENTRY_POINT_GROUP,
    AdvertisedBundles,
    advertised_bundles,
    installed_bundles,
)
from .required_bundle import RequiredBundle, required_bundle

__all__ = [
    "BUNDLES_ENTRY_POINT_GROUP",
    "KERNEL_BUNDLE",
    "AdvertisedBundles",
    "Bundle",
    "BundleMetadata",
    "NoConfig",
    "RequiredBundle",
    "advertised_bundles",
    "as_bundle",
    "installed_bundles",
    "required_bundle",
]
