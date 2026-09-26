"""Focused branch-coverage tests for todo 26.

Every test here pins one currently-uncovered branch in ``src/``. If a test fails after a
refactor, the branch it names has changed — read the test's docstring, decide whether the
behavior it locks is still desired, then adjust the test to prove the new behavior. Do NOT
delete a test to silence it: coverage is a floor, not a suggestion.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import anyio
import pytest

from xtr_dependency_injection import Kernel
from xtr_dependency_injection.builder.conflict_policy import record_alias
from xtr_dependency_injection.builder.definition import Origin
from xtr_dependency_injection.exception import DuplicateServiceError
from xtr_dependency_injection.exception._naming import (
    key_name,
    qualified_name,
    type_name,
)
from xtr_dependency_injection.runtime.bind_callable import _signature_of, bind_callable
from xtr_dependency_injection.testing import boot_for_test

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.definition import ServiceKey


class _AliasA:
    pass


class _AliasTarget:
    pass


def _bundle_origin(name: str) -> Origin:
    return Origin(kind="bundle", name=name)


def _app_origin() -> Origin:
    return Origin(kind="app", name="app")


def test_record_alias_lets_the_app_override_a_bundle_alias() -> None:
    aliases: dict[ServiceKey, ServiceKey] = {}
    origins: dict[ServiceKey, Origin] = {}
    key: ServiceKey = (_AliasA, None)
    target: ServiceKey = (_AliasTarget, None)

    record_alias(aliases, origins, key, target, _bundle_origin("mail"))
    record_alias(aliases, origins, key, target, _app_origin())

    assert aliases[key] == target
    assert origins[key].kind == "app"


def test_record_alias_keeps_the_app_when_a_bundle_tries_to_override() -> None:
    aliases: dict[ServiceKey, ServiceKey] = {}
    origins: dict[ServiceKey, Origin] = {}
    key: ServiceKey = (_AliasA, None)
    target: ServiceKey = (_AliasTarget, None)

    record_alias(aliases, origins, key, target, _app_origin())
    record_alias(aliases, origins, key, target, _bundle_origin("mail"))

    assert origins[key].kind == "app"


def test_record_alias_raises_when_two_bundles_claim_the_same_alias() -> None:
    aliases: dict[ServiceKey, ServiceKey] = {}
    origins: dict[ServiceKey, Origin] = {}
    key: ServiceKey = (_AliasA, None)
    target: ServiceKey = (_AliasTarget, None)

    record_alias(aliases, origins, key, target, _bundle_origin("one"))

    with pytest.raises(DuplicateServiceError):
        record_alias(aliases, origins, key, target, _bundle_origin("two"))


def test_bind_callable_refuses_a_foreign_container_interface() -> None:
    class Foreign:
        async def get(self, service: type, /, qualifier: object = None) -> object:
            _ = (service, qualifier)
            return object()

        def has(self, service: type, /, qualifier: object = None) -> bool:
            _ = (service, qualifier)
            return False

        def get_parameter(self, name: str, /) -> object:
            _ = name
            return None

        def has_parameter(self, name: str, /) -> bool:
            _ = name
            return False

    with pytest.raises(TypeError, match="kernel-provided container"):
        _ = bind_callable(Foreign(), lambda: None)  # pyright: ignore[reportArgumentType]


def test_bind_callable_refuses_a_class_without_call() -> None:
    """A class with no ``__call__`` has no signature for wireup to fill."""

    class NotCallable:
        pass

    async def _drive() -> None:
        kernel = Kernel("xtr_dependency_injection", bundles={}, resources=())
        async with await boot_for_test(kernel) as booted:
            with pytest.raises(TypeError, match="__call__"):
                _ = bind_callable(booted.container, NotCallable)

    anyio.run(_drive)


def test_qualified_name_falls_back_to_repr_for_a_module_less_object() -> None:
    """Objects without ``__module__`` or ``__qualname__`` render as ``repr(obj)``."""

    class Bare:
        pass

    bare = Bare()
    # Instances have __class__.__module__ but not their own __module__/__qualname__.
    assert qualified_name(bare) == repr(bare)


def test_type_name_falls_back_to_repr_for_an_unnamed_object() -> None:
    """A plain instance without qualname reads as ``repr``."""
    value = object()
    assert type_name(value) == repr(value)


def test_type_name_uses_module_colon_qualname_for_a_plain_function() -> None:
    def some_factory() -> int:
        return 0

    rendered = type_name(some_factory)
    assert ":" in rendered
    assert rendered.endswith("some_factory")


def test_key_name_renders_a_qualified_key() -> None:
    class Widget:
        pass

    plain = key_name((Widget, None))
    qualified = key_name((Widget, "left"))
    assert "Widget" in plain
    assert "'left'" in qualified


def test_signature_of_a_class_strips_self() -> None:
    """The internal helper drops ``self`` for a class target, so wireup fills only params."""

    class Handler:
        def __call__(self, message: str) -> str:
            return message

    signature = _signature_of(Handler)
    parameters = list(signature.parameters)
    assert parameters == ["message"]
    _ = inspect.signature  # keep the import used by other assertions
