from __future__ import annotations

import copy
import types

import pytest

from xtr_dependency_injection.bundle._absent_bundle import AbsentBundle

_TOOLS = AbsentBundle("acme_tools.bundle", "ToolsBundle")


def test_it_is_named_by_the_module_and_the_name_it_was_imported_by() -> None:
    assert _TOOLS.target == "acme_tools.bundle:ToolsBundle"


def test_it_keys_a_mapping_as_any_stand_in_for_the_same_class_does() -> None:
    listed = {_TOOLS: {"dev": True}}

    assert listed[AbsentBundle("acme_tools.bundle", "ToolsBundle")] == {"dev": True}


def test_reading_an_attribute_of_it_raises_the_missing_module() -> None:
    with pytest.raises(ModuleNotFoundError) as caught:
        _ = _TOOLS.metadata

    assert caught.value.name == "acme_tools.bundle"


def test_calling_it_raises_the_missing_module() -> None:
    with pytest.raises(ModuleNotFoundError) as caught:
        _TOOLS()

    assert caught.value.name == "acme_tools.bundle"


def test_subclassing_it_raises_the_missing_module() -> None:
    with pytest.raises(ModuleNotFoundError) as caught:
        # Deriving from what is not a class is the case under test.
        _ = types.new_class("Derived", (_TOOLS,))  # ty: ignore[invalid-base]

    assert caught.value.name == "acme_tools.bundle"


def test_a_protocol_probing_it_for_an_optional_hook_finds_none() -> None:
    assert copy.deepcopy(_TOOLS) == _TOOLS
