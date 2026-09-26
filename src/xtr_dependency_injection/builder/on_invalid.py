"""Shared ``OnInvalid`` enum, defined here to avoid a builder / decorator import cycle.

Public users see ``OnInvalid`` at :mod:`xtr_dependency_injection` and
:mod:`xtr_dependency_injection.decorator.as_decorator` - both re-export the
class defined here. It lives under ``builder`` because
:class:`~xtr_dependency_injection.builder.definition.Decorates` needs it at
class-definition time, and pulling it from ``decorator/`` would drag the
whole decorator package (whose submodules import ``builder.definition``)
into a circular import.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["OnInvalid"]


class OnInvalid(Enum):
    """What a decorator does when the decorated service is not defined.

    :attr:`EXCEPTION` fails the build, :attr:`IGNORE` drops the decorator,
    and :attr:`NULL` keeps it under the target key with ``None`` for its
    inner parameter.
    """

    EXCEPTION = "exception"
    """Fail the build with :class:`UnknownServiceError` (the default)."""

    IGNORE = "ignore"
    """Drop the decorator - it never enters the container."""

    NULL = "null"
    """Keep the decorator under the target key; feed ``None`` to its inner parameter."""
