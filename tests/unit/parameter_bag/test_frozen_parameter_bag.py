from __future__ import annotations

import pytest

from xtr_dependency_injection.exception import BuilderFrozenError
from xtr_dependency_injection.parameter_bag import FrozenParameterBag


def test_it_holds_resolved_parameters() -> None:
    bag = FrozenParameterBag({"a": {"b": "%kept%"}})

    assert bag.get("a.b") == "%kept%"
    assert bag.is_resolved()


@pytest.mark.parametrize("operation", ["clear", "add", "set", "remove"])
def test_every_change_is_refused(operation: str) -> None:
    bag = FrozenParameterBag({"a": 1})
    arguments = {"clear": (), "add": ({"b": 2},), "set": ("b", 2), "remove": ("a",)}[operation]

    with pytest.raises(BuilderFrozenError, match=operation):
        getattr(bag, operation)(*arguments)
