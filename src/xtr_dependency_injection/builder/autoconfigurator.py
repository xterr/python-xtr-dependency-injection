"""Autoconfiguration: a bundle reacting to what the scan found.

A bundle registers a *reader* — metadata found on a candidate, empty for no
match — and an *apply*, called once per metadata item. The console bundle
reads ``@as_command`` descriptors and registers each command; the scan never
needs to know what a command is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from xtr_dependency_injection.scan.scanned_object import ScannedObject

    from .service_configurator import ServiceConfigurator

__all__ = ["Apply", "Autoconfigurator", "Reader", "run_autoconfigurators"]

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


def run_autoconfigurators(
    autoconfigurators: Sequence[Autoconfigurator],
    candidates: Sequence[ScannedObject],
    configurator_for: Callable[[str, ScannedObject], ServiceConfigurator],
) -> None:
    """Run every autoconfigurator over every candidate.

    The outer loop is over autoconfigurators, in bundle order and then
    registration order; the inner loop over candidates, in scan order.

    Args:
        autoconfigurators: What bundles registered while loading.
        candidates: The service candidates of every scan.
        configurator_for: The configurator ``apply`` receives, for a bundle
            and the candidate it applies to.

    Raises:
        Exception: Whatever a reader raised — a reader failing is a bug —
            with a note naming the reader and the candidate.
    """
    for autoconfigurator in autoconfigurators:
        for candidate in candidates:
            try:
                found = tuple(autoconfigurator.reader(candidate.obj))
            except Exception as error:
                reader = getattr(autoconfigurator.reader, "__qualname__", "reader")
                where = f"of bundle {autoconfigurator.owner} on {candidate.name}"
                error.add_note(f"raised by autoconfigure reader {reader} {where}")
                raise
            if not found:
                continue
            services = configurator_for(autoconfigurator.owner, candidate)
            for metadata in found:  # pyright: ignore[reportAny]
                autoconfigurator.apply(candidate.obj, metadata, services)
