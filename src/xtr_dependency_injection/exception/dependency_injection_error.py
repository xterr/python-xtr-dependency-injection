"""The root every error in this package derives from."""

from __future__ import annotations

__all__ = ["DependencyInjectionError"]


class DependencyInjectionError(Exception):
    """Base class for every error raised by this package.

    Catch this to handle anything the kernel can go wrong with; catch a
    subclass to handle one cause. Every subclass carries the data a caller
    needs as typed attributes and composes its own message from them.
    """
