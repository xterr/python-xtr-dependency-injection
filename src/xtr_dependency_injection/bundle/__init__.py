"""Declaring bundles: the base class, its decorator, and what the decorator records."""

from __future__ import annotations

from .as_bundle import as_bundle
from .bundle import KERNEL_BUNDLE, Bundle, NoConfig
from .bundle_metadata import BundleMetadata
from .required_bundle import RequiredBundle, required_bundle

__all__ = [
    "KERNEL_BUNDLE",
    "Bundle",
    "BundleMetadata",
    "NoConfig",
    "RequiredBundle",
    "as_bundle",
    "required_bundle",
]
