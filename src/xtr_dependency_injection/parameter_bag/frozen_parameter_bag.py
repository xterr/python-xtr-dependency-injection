"""Parameters that can no longer change: the container's, once it is compiled."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

from typing_extensions import override

from xtr_dependency_injection.exception import BuilderFrozenError

from .parameter_bag import ParameterBag

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["FrozenParameterBag"]


class FrozenParameterBag(ParameterBag):
    """A resolved :class:`ParameterBag` refusing every change."""

    __slots__: tuple[str, ...] = ()

    _resolved: bool

    def __init__(self, parameters: Mapping[str, object] | None = None) -> None:
        """Hold ``parameters``, already resolved."""
        super().__init__()
        if parameters is not None:
            ParameterBag.add(self, parameters)
        self._resolved = True

    @override
    def clear(self) -> NoReturn:
        raise BuilderFrozenError("clear")

    @override
    def add(self, parameters: Mapping[str, object], /) -> NoReturn:
        raise BuilderFrozenError("add")

    @override
    def set(self, name: str, value: object, /) -> NoReturn:
        raise BuilderFrozenError("set")

    @override
    def remove(self, name: str, /) -> NoReturn:
        raise BuilderFrozenError("remove")
