"""Running every bundle's autoconfigurator over every scanned service candidate.

A bundle registers a reader and a callback with
``ContainerBuilder.register_attribute_for_autoconfiguration``; this pass calls
the callback once per metadata item the reader finds on a candidate, with the
registering bundle's :class:`ServiceConfigurator`, so what it defines carries
that bundle's origin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from xtr_dependency_injection.builder._origins import origin_of
from xtr_dependency_injection.builder.definition import Origin

from ._state import state_of

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["AttributeAutoconfigurationPass"]


@final
class AttributeAutoconfigurationPass:
    """Calls each autoconfigurator on every candidate its reader finds metadata on.

    The outer loop is over autoconfigurators, in bundle order then
    registration order; the inner loop over candidates, in scan order.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Run every autoconfigurator over every candidate.

        Raises:
            Exception: Whatever a reader raised — a reader failing is a bug —
                with a note naming the reader and the candidate.
        """
        # Imported here: the build state this pass writes into imports the
        # compiler, and so this module, while it is itself being defined.
        from xtr_dependency_injection.builder.service_configurator import (  # noqa: PLC0415
            ServiceConfigurator,
        )

        state = state_of(builder)
        for autoconfigurator in state.autoconfigurators:
            for candidate in state.candidates:
                try:
                    found = tuple(autoconfigurator.reader(candidate.obj))
                except Exception as error:
                    reader = getattr(autoconfigurator.reader, "__qualname__", "reader")
                    where = f"of bundle {autoconfigurator.owner} on {candidate.name}"
                    error.add_note(f"raised by autoconfigure reader {reader} {where}")
                    raise
                if not found:
                    continue
                base = origin_of(autoconfigurator.owner)
                origin = Origin(base.kind, base.name, f"via autoconfigure of {candidate.name}")
                services = ServiceConfigurator(state, origin)
                for metadata in found:
                    autoconfigurator.apply(candidate.obj, metadata, services)
