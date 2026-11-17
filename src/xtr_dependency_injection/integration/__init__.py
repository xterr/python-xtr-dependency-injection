"""Integrations with the underlying container engine and with web frameworks.

This package is the one place where the engine (``wireup``) surfaces in the
public API: everything else stays behind :class:`ContainerInterface`.
:func:`detached_context` is the context a server serves a new connection in.
"""

from __future__ import annotations

from .detached_context import detached_context, register_detached_variable

__all__ = ["detached_context", "register_detached_variable"]
