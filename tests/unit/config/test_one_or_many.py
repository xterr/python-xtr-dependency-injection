from __future__ import annotations

from xtr_dependency_injection import one_or_many


def test_a_list_or_a_tuple_is_several_entries() -> None:
    assert one_or_many(["a", "b"]) == ("a", "b")
    assert one_or_many(("a",)) == ("a",)
    assert one_or_many([]) == ()


def test_anything_else_is_one_entry_a_string_included() -> None:
    assert one_or_many("redis://a") == ("redis://a",)
    assert one_or_many(3) == (3,)
