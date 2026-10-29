"""A bundles module that imports a module of the application's that does not exist.

Only a package outside the application is stood in for when it is missing: the
application's own modules are all there, or it is broken.
"""

from __future__ import annotations

import importlib

_ = importlib.import_module("tests.fixtures.bundles_modules.deep_import.not_there")

BUNDLES: dict[object, object] = {}
