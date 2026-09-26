"""Autoconfiguration: a bundle reacting to what the scan found.

A bundle registers a *reader* — metadata found on a candidate, empty for no
match — and an *apply*, called once per metadata item. The console bundle
reads ``@as_command`` descriptors and registers each command; the scan never
needs to know what a command is. ``AttributeAutoconfigurationPass`` runs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .service_configurator import ServiceConfigurator

__all__ = ["Apply", "Autoconfigurator", "Reader"]

# What a reader finds is only meaningful to the bundle that reads it, so the
# builder passes it through untyped.
Reader: TypeAlias = "Callable[[object], Iterable[Any]]"  # pyright: ignore[reportExplicitAny]
Apply: TypeAlias = "Callable[[object, Any, ServiceConfigurator], None]"  # pyright: ignore[reportExplicitAny]


@dataclass(frozen=True, slots=True)
class Autoconfigurator:
    """One ``services.autoconfigure(reader, apply)`` call, and the bundle that made it."""

    owner: str
    reader: Reader
    apply: Apply
