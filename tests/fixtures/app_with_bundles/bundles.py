"""The ``bundles.py`` the kernel imports by convention from the application package."""

from __future__ import annotations

from . import ListedBundle

BUNDLES = {ListedBundle: {"all": True}}
