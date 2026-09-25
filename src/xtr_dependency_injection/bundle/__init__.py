"""Declaring bundles: the base class, its decorator, and what the decorator records."""

from __future__ import annotations

from .as_bundle import as_bundle
from .bundle import Bundle, NoConfig
from .bundle_metadata import BundleMetadata

__all__ = ["Bundle", "BundleMetadata", "NoConfig", "as_bundle"]
