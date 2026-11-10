"""Filling the application's cache ahead of its first use.

A cache warmer is a service implementing :class:`CacheWarmerInterface`; the
kernel tags it ``kernel.cache_warmer`` and hands every one to the
:class:`CacheWarmerAggregate` it registers, highest tag ``priority`` first.
:class:`CacheWarmer` is a base for a warmer that writes files.
:class:`WarmedCache` records which build the warmers last filled the cache for,
so the kernel warms it at boot only while it is cold.
"""

from __future__ import annotations

from .cache_warmer import CacheWarmer
from .cache_warmer_aggregate import CacheWarmerAggregate
from .cache_warmer_interface import CacheWarmerInterface
from .warmable_interface import WarmableInterface
from .warmed_cache import WarmedCache

__all__ = [
    "CacheWarmer",
    "CacheWarmerAggregate",
    "CacheWarmerInterface",
    "WarmableInterface",
    "WarmedCache",
]
