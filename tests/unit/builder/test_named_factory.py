from __future__ import annotations

from typing import TYPE_CHECKING, cast

from xtr_dependency_injection import named_factory

if TYPE_CHECKING:
    import types


def _factory_for(resource: str) -> types.FunctionType:
    def store() -> str:
        return resource

    return cast("types.FunctionType", named_factory(store, f"lock_store_{resource}"))


def test_each_factory_carries_the_name_it_was_given_and_still_works() -> None:
    reports = _factory_for("reports")

    assert reports.__name__ == "lock_store_reports"
    assert reports.__qualname__ == "lock_store_reports"
    assert reports() == "reports"
