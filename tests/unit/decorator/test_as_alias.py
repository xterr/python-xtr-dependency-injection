from __future__ import annotations

from xtr_dependency_injection.decorator.as_alias import AliasMarker, aliases_of, as_alias


class IfaceA:
    pass


class IfaceB:
    pass


def test_aliases_of_returns_empty_when_unmarked() -> None:
    class Plain:
        pass

    assert aliases_of(Plain) == ()


def test_as_alias_records_one_alias() -> None:
    @as_alias(IfaceA)
    class Impl:
        pass

    assert aliases_of(Impl) == (AliasMarker(alias=IfaceA, qualifier=None),)


def test_as_alias_is_repeatable_and_carries_qualifiers() -> None:
    @as_alias(IfaceA, qualifier="a")
    @as_alias(IfaceB, qualifier="b")
    class Impl:
        pass

    got = aliases_of(Impl)

    assert set(got) == {
        AliasMarker(alias=IfaceA, qualifier="a"),
        AliasMarker(alias=IfaceB, qualifier="b"),
    }
    assert len(got) == 2


def test_a_subclass_does_not_inherit_the_aliases() -> None:
    @as_alias(IfaceA)
    class Parent:
        pass

    class Child(Parent):
        pass

    assert aliases_of(Child) == ()
