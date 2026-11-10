"""Emptying the caches that live outside the cache directory.

A cache clearer is a service implementing :class:`CacheClearerInterface`; the
kernel tags it ``kernel.cache_clearer`` and hands every one to the
:class:`ChainCacheClearer` it registers, highest tag ``priority`` first.
"""

from __future__ import annotations

from .cache_clearer_interface import CacheClearerInterface
from .chain_cache_clearer import ChainCacheClearer

__all__ = ["CacheClearerInterface", "ChainCacheClearer"]
