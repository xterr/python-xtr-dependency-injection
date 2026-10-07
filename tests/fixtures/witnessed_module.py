"""A module whose import is observable: it records itself in the witness list.

Importing it is the side effect a test wants to prove never happened, and
:data:`MARKER` is the attribute an expression would name to cause it.
"""

from __future__ import annotations

from tests.fixtures.import_witness import WITNESSED

__all__ = ["MARKER"]

MARKER = "the module was imported"

WITNESSED.append(__name__)
