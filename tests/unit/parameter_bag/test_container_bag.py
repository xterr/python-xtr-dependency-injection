from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from typing_extensions import override
from xtr_service_contracts import ContainerInterface

from xtr_dependency_injection.parameter_bag import ContainerBag, ContainerBagInterface

if TYPE_CHECKING:
    from collections.abc import Hashable

T = TypeVar("T")


class FakeContainer(ContainerInterface):
    def __init__(self, parameters: dict[str, object]) -> None:
        self.parameters: dict[str, object] = parameters

    @override
    async def get(self, service: type[T], /, qualifier: Hashable | None = None) -> T:
        del service, qualifier
        raise NotImplementedError

    @override
    def has(self, service: type[object], /, qualifier: Hashable | None = None) -> bool:
        del service, qualifier
        return False

    @override
    def get_parameter(self, name: str, /) -> object:
        return self.parameters[name]

    @override
    def has_parameter(self, name: str, /) -> bool:
        return name in self.parameters


def test_it_reads_through_the_container_and_lists_what_it_was_given() -> None:
    bag = ContainerBag(FakeContainer({"a.b": 1}), {"a": {"b": 1}})

    assert isinstance(bag, ContainerBagInterface)
    assert bag.get("a.b") == 1
    assert bag.has("a.b")
    assert not bag.has("a.c")
    assert bag.all() == {"a": {"b": 1}}
    assert bag.resolve_value("%a.b%") == 1
