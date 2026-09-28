"""A bundles module that imports a module that does not exist."""

from __future__ import annotations

import importlib

_ = importlib.import_module("xtr_no_such_module_for_bundles")

BUNDLES: dict[object, object] = {}
