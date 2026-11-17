"""Handing the kernel's unit participants every ``kernel.unit_participant`` service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from xtr_service_contracts import UnitParticipantInterface

from xtr_dependency_injection.runtime._unit_scope import UnitParticipants

from .priority_tagged_service import alias_by_priority

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

__all__ = ["UNIT_PARTICIPANT_TAG", "UnitParticipantPass"]

UNIT_PARTICIPANT_TAG: Final = "kernel.unit_participant"
"""The tag a unit participant carries; an optional ``priority`` attribute, higher told first."""


@final
class UnitParticipantPass:
    """Hands :class:`UnitParticipants` every service tagged :data:`UNIT_PARTICIPANT_TAG`.

    Registered by the kernel bundle, after every bundle's ``process`` hook, so a
    participant a bundle tags there is told too.
    """

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Alias every tagged participant, in priority order, and give the holder their names.

        Raises:
            InvalidDefinitionError: When a tag's ``priority`` is not an integer.
        """
        names = alias_by_priority(builder, UNIT_PARTICIPANT_TAG, UnitParticipantInterface)
        _ = builder.get_definition(UnitParticipants).set_argument("participant_names", names)
