"""Tests for the before/after sorter.

Seed order, before/after moves, priority ties, cycles, and unsatisfiable constraints.
"""

from __future__ import annotations

import pytest

from xtr_dependency_injection.compiler.before_after_sorter import sort, sort_with_priorities
from xtr_dependency_injection.exception.service_order_error import ServiceOrderError


def test_seed_order_is_kept_when_there_is_no_constraint() -> None:
    assert sort(["a", "b", "c"], {}) == ["a", "b", "c"]


def test_before_moves_the_constrained_item_not_its_target() -> None:
    assert sort(["a", "b", "c"], {"c": {"before": ["a"]}}) == ["c", "a", "b"]


def test_after_moves_the_constrained_item_not_its_target() -> None:
    assert sort(["a", "b", "c"], {"a": {"after": ["b"]}}) == ["b", "a", "c"]


def test_after_is_the_mirror_of_before() -> None:
    with_before = sort(["a", "b", "c"], {"c": {"before": ["a"]}})
    with_after = sort(["a", "b", "c"], {"a": {"after": ["c"]}})

    assert with_before == with_after
    assert with_after == ["c", "a", "b"]


def test_an_item_is_inserted_between_two_others() -> None:
    assert sort(["b", "c", "e"], {"e": {"after": ["b"], "before": ["c"]}}) == ["b", "e", "c"]


def test_only_the_constrained_item_moves_in_a_longer_list() -> None:
    assert sort(["a", "b", "c", "d", "e", "j"], {"j": {"before": ["b"]}}) == [
        "a",
        "j",
        "b",
        "c",
        "d",
        "e",
    ]


def test_constraints_are_transitive() -> None:
    assert sort(
        ["a", "b", "c"],
        {"b": {"before": ["a"]}, "c": {"before": ["b"]}},
    ) == ["c", "b", "a"]


def test_references_to_unknown_items_are_ignored() -> None:
    assert sort(
        ["a", "b"],
        {"a": {"before": ["not_in_the_collection"]}, "b": {"after": ["gone_too"]}},
    ) == ["a", "b"]


def test_constraints_on_unknown_items_are_ignored() -> None:
    assert sort(["a", "b"], {"not_in_the_collection": {"before": ["a"]}}) == ["a", "b"]


def test_multiple_targets_are_supported() -> None:
    assert sort(["a", "b", "c"], {"c": {"before": ["a", "b"]}}) == ["c", "a", "b"]


def test_priorities_seed_the_order_and_a_missing_one_counts_as_zero() -> None:
    assert sort_with_priorities({"a": None, "b": 5, "c": -5}, {}) == {"b": 5, "a": 0, "c": -5}


def test_an_item_without_priority_adopts_the_one_its_placement_needs() -> None:
    assert sort_with_priorities({"a": 10, "b": None, "d": 5}, {"b": {"before": ["a"]}}) == {
        "b": 10,
        "a": 10,
        "d": 5,
    }
    assert sort_with_priorities({"a": 10, "b": None, "d": -5}, {"b": {"after": ["d"]}}) == {
        "a": 10,
        "d": -5,
        "b": -5,
    }


def test_an_item_without_priority_stays_at_zero_when_that_fits() -> None:
    assert sort_with_priorities(
        {"a": 10, "b": None, "d": -5}, {"b": {"after": ["a"], "before": ["d"]}}
    ) == {"a": 10, "b": 0, "d": -5}


def test_an_item_without_priority_between_two_others_takes_the_closest_to_zero() -> None:
    assert sort_with_priorities(
        {"a": 100, "b": None, "d": 50}, {"b": {"after": ["a"], "before": ["d"]}}
    ) == {"a": 100, "b": 50, "d": 50}


def test_an_item_without_priority_can_be_moved_by_the_constraint_of_another() -> None:
    assert sort_with_priorities({"a": 10, "b": None}, {"a": {"after": ["b"]}}) == {
        "b": 10,
        "a": 10,
    }


def test_explicit_priorities_are_never_changed() -> None:
    assert sort_with_priorities({"a": 0, "b": 0, "c": 0}, {"c": {"before": ["a"]}}) == {
        "c": 0,
        "a": 0,
        "b": 0,
    }


def test_a_constraint_already_satisfied_by_priorities_changes_nothing() -> None:
    assert sort_with_priorities({"a": 10, "b": 0}, {"a": {"before": ["b"]}}) == {"a": 10, "b": 0}


def test_a_before_constraint_contradicted_by_an_explicit_priority_is_reported() -> None:
    with pytest.raises(
        ServiceOrderError,
        match=(
            r'The priority of "b" \(0\) contradicts its "before" constraint on "a" \(10\): '
            r"raise it to 10 or more, remove it, or drop the constraint\."
        ),
    ):
        _ = sort_with_priorities({"a": 10, "b": 0}, {"b": {"before": ["a"]}})


def test_an_after_constraint_contradicted_by_an_explicit_priority_is_reported() -> None:
    with pytest.raises(
        ServiceOrderError,
        match=(
            r'The priority of "a" \(10\) contradicts its "after" constraint on "b" \(0\): '
            r"lower it to 0 or less, remove it, or drop the constraint\."
        ),
    ):
        _ = sort_with_priorities({"a": 10, "b": 0}, {"a": {"after": ["b"]}})


def test_a_contradiction_through_an_item_without_priority_is_reported() -> None:
    with pytest.raises(
        ServiceOrderError,
        match=(
            r'The "before"/"after" constraints on "f" cannot be satisfied: it would need '
            r'a priority of at least 100 to run before "a" and at most 50 to run after "b"\.'
        ),
    ):
        _ = sort_with_priorities(
            {"a": 100, "b": 50, "f": None},
            {"f": {"after": ["b"], "before": ["a"]}},
        )


def test_aliases_are_resolved_for_the_contradiction_check() -> None:
    with pytest.raises(
        ServiceOrderError,
        match=r'The priority of "b" \(0\) contradicts its "before" constraint on "a" \(10\)',
    ):
        _ = sort_with_priorities(
            {"a": 10, "b": 0},
            {"b": {"before": ["Some\\Class"]}},
            {"Some\\Class": ["a"]},
        )


def test_an_explicit_priority_constraining_a_free_item_moves_the_free_one() -> None:
    assert sort_with_priorities({"x": 100, "b": None, "a": -200}, {"a": {"before": ["b"]}}) == {
        "x": 100,
        "a": -200,
        "b": -200,
    }


def test_bounds_propagate_through_free_items() -> None:
    assert sort_with_priorities(
        {"z": None, "f1": None, "f2": None, "a": 100},
        {"f1": {"before": ["f2"]}, "f2": {"before": ["a"]}},
    ) == {"f1": 100, "f2": 100, "a": 100, "z": 0}


def test_a_direct_cycle_is_reported() -> None:
    with pytest.raises(
        ServiceOrderError,
        match=r'Cycle detected in the "before"/"after" constraints: "a" -> "b" -> "a"\.',
    ):
        _ = sort(["a", "b"], {"a": {"before": ["b"]}, "b": {"before": ["a"]}})


def test_an_indirect_cycle_is_reported() -> None:
    with pytest.raises(
        ServiceOrderError,
        match=(
            r'Cycle detected in the "before"/"after" constraints: '
            r'"a" -> "c" -> "b" -> "a"\.'
        ),
    ):
        _ = sort(
            ["a", "b", "c"],
            {
                "a": {"before": ["b"]},
                "b": {"before": ["c"]},
                "c": {"before": ["a"]},
            },
        )


def test_an_item_referencing_itself_is_ignored() -> None:
    assert sort(["a", "b"], {"a": {"before": ["a"]}}) == ["a", "b"]


def test_an_alias_designates_the_items_it_stands_for() -> None:
    assert sort(
        ["a", "b", "c"],
        {"c": {"before": ["Some\\Class"]}},
        {"Some\\Class": ["a"]},
    ) == ["c", "a", "b"]


def test_an_alias_can_designate_several_items() -> None:
    assert sort(
        ["a", "b", "c"],
        {"c": {"before": ["Some\\Class"]}},
        {"Some\\Class": ["a", "b"]},
    ) == ["c", "a", "b"]


def test_an_alias_resolving_to_the_item_itself_is_ignored() -> None:
    assert sort(
        ["a", "b"],
        {"a": {"before": ["Some\\Class"]}},
        {"Some\\Class": ["a"]},
    ) == ["a", "b"]
