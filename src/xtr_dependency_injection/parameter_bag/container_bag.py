"""The compiled container's parameters as a service: inject :class:`ContainerBagInterface`."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from .container_bag_interface import ContainerBagInterface
from .frozen_parameter_bag import FrozenParameterBag

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_service_contracts import ContainerInterface

__all__ = ["ContainerBag"]


@final
class ContainerBag(FrozenParameterBag, ContainerBagInterface):
    """Reads parameters through the container, so an environment placeholder is refused raw."""

    __slots__: tuple[str, ...] = ("_container",)

    def __init__(self, container: ContainerInterface, parameters: Mapping[str, object]) -> None:
        """Answer ``get``/``has`` through ``container``; ``parameters`` are what ``all`` returns."""
        super().__init__(parameters)
        self._container = container

    @override
    def get(self, name: str, /) -> object:
        return self._container.get_parameter(name)

    @override
    def has(self, name: str, /) -> bool:
        return self._container.has_parameter(name)
