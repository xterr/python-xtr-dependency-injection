from __future__ import annotations

import pytest

from xtr_dependency_injection.config.parameters import (
    call_parameters,
    is_parameters,
    merge_parameters,
    parameters,
)
from xtr_dependency_injection.exception import ConfigProviderError, ParameterConflictError


def test_parameters_marks_the_function() -> None:
    @parameters
    def provide() -> dict[str, object]:
        return {}

    assert is_parameters(provide)


def test_an_unmarked_function_is_not_parameters() -> None:
    def provide() -> dict[str, object]:
        return {}

    assert not is_parameters(provide)


def test_nested_mappings_merge() -> None:
    merged = merge_parameters(
        [("kernel", {"kernel": {"env": "dev"}}), ("app", {"kernel": {"name": "app"}, "x": 1})]
    )

    assert merged == {"kernel": {"env": "dev", "name": "app"}, "x": 1}


def test_a_leaf_set_twice_is_refused() -> None:
    with pytest.raises(ParameterConflictError) as caught:
        _ = merge_parameters([("bundle a", {"db": {"url": "a"}}), ("app", {"db": {"url": "b"}})])

    assert (caught.value.path, caught.value.first, caught.value.second) == (
        ("db", "url"),
        "bundle a",
        "app",
    )


def test_a_leaf_replacing_a_mapping_is_refused() -> None:
    with pytest.raises(ParameterConflictError):
        _ = merge_parameters([("a", {"db": {"url": "a"}}), ("b", {"db": "flat"})])


def test_a_none_leaf_still_counts_as_set() -> None:
    with pytest.raises(ParameterConflictError):
        _ = merge_parameters([("a", {"db": None}), ("b", {"db": 1})])


def test_a_dotted_key_is_refused() -> None:
    with pytest.raises(ConfigProviderError, match=r"without '\.'"):
        _ = merge_parameters([("app", {"db.url": "x"})])


def test_a_non_string_key_is_refused() -> None:
    with pytest.raises(ConfigProviderError, match="must be a string"):
        # Deliberately the wrong type: keys come from untyped user mappings.
        _ = merge_parameters([("app", {1: "x"})])  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]


def test_merging_does_not_mutate_the_sources() -> None:
    source = {"db": {"url": "a"}}

    _ = merge_parameters([("a", source), ("b", {"db": {"user": "u"}})])

    assert source == {"db": {"url": "a"}}


def test_calling_a_provider_returns_its_mapping() -> None:
    @parameters
    def provide() -> dict[str, object]:
        return {"x": 1}

    assert call_parameters(provide) == {"x": 1}


def test_a_provider_returning_a_non_mapping_is_refused() -> None:
    @parameters
    def provide() -> object:
        return [1]

    with pytest.raises(ConfigProviderError, match="not a mapping"):
        _ = call_parameters(provide)


def test_a_provider_taking_arguments_is_refused() -> None:
    @parameters
    def provide(_extra: int) -> dict[str, object]:
        return {}

    with pytest.raises(ConfigProviderError, match="takes no arguments"):
        _ = call_parameters(provide)
