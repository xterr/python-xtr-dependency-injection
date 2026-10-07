"""Walking and rebuilding configuration values, cycles included."""

from __future__ import annotations

from xtr_dependency_injection.config._walk import rebuild


def _identity(value: object) -> object:
    return value


def test_a_self_referential_list_does_not_recurse_forever() -> None:
    cyclic: list[object] = ["a"]
    cyclic.append(cyclic)

    rebuilt = rebuild(cyclic, _identity)

    assert rebuilt is cyclic


def test_a_self_referential_mapping_does_not_recurse_forever() -> None:
    cyclic: dict[str, object] = {"key": "value"}
    cyclic["self"] = cyclic

    rebuilt = rebuild(cyclic, _identity)

    assert rebuilt is cyclic


def test_a_shared_child_is_still_rebuilt_at_each_occurrence() -> None:
    shared = ["x"]
    outer = [shared, shared]

    rebuilt = rebuild(outer, lambda value: "y" if value == "x" else value)

    assert rebuilt == [["y"], ["y"]]
