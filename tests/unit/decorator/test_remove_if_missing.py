from __future__ import annotations

import pytest

from xtr_dependency_injection.decorator.remove_if_missing import (
    REMOVE_IF_MISSING_TAG,
    markers_of,
    remove_if_missing,
)


class Peer:
    pass


def test_the_tag_name_is_container_remove_if_missing() -> None:
    assert REMOVE_IF_MISSING_TAG == "container.remove_if_missing"


def test_remove_if_missing_records_a_service_condition() -> None:
    @remove_if_missing(service=Peer)
    class Owner:
        pass

    assert markers_of(Owner) == [{"service": Peer}]


def test_remove_if_missing_records_a_service_and_qualifier() -> None:
    @remove_if_missing(service=Peer, qualifier="main")
    class Owner:
        pass

    assert markers_of(Owner) == [{"service": Peer, "qualifier": "main"}]


def test_remove_if_missing_records_a_class_path() -> None:
    @remove_if_missing(class_="some_module:SomeClass")
    class Owner:
        pass

    assert markers_of(Owner) == [{"class_": "some_module:SomeClass"}]


def test_remove_if_missing_records_class_and_package() -> None:
    @remove_if_missing(class_="pkg:Cls", package="dist-name")
    class Owner:
        pass

    assert markers_of(Owner) == [{"class_": "pkg:Cls", "package": "dist-name"}]


def test_remove_if_missing_is_repeatable() -> None:
    @remove_if_missing(service=Peer)
    @remove_if_missing(class_="pkg:Cls")
    class Owner:
        pass

    assert markers_of(Owner) == [{"class_": "pkg:Cls"}, {"service": Peer}]


def test_remove_if_missing_without_any_condition_raises_at_decoration_time() -> None:
    with pytest.raises(TypeError, match="requires one of"):
        _ = remove_if_missing()


def test_remove_if_missing_qualifier_without_service_raises() -> None:
    with pytest.raises(TypeError, match="qualifier="):
        _ = remove_if_missing(class_="pkg:Cls", qualifier="x")


def test_remove_if_missing_records_a_package_alone() -> None:
    @remove_if_missing(package="dist")
    class Owner:
        pass

    assert markers_of(Owner) == [{"package": "dist"}]


def test_remove_if_missing_records_service_and_class_together() -> None:
    @remove_if_missing(service=Peer, class_="pkg:Cls")
    class Owner:
        pass

    assert markers_of(Owner) == [{"service": Peer, "class_": "pkg:Cls"}]


def test_remove_if_missing_records_all_three_conditions_in_one_call() -> None:
    @remove_if_missing(service=Peer, class_="pkg:Cls", package="dist")
    class Owner:
        pass

    assert markers_of(Owner) == [{"service": Peer, "class_": "pkg:Cls", "package": "dist"}]


def test_markers_of_returns_empty_for_an_unmarked_class() -> None:
    class Plain:
        pass

    assert markers_of(Plain) == []


def test_a_subclass_does_not_inherit_its_parents_markers() -> None:
    @remove_if_missing(service=Peer)
    class Parent:
        pass

    class Child(Parent):
        pass

    assert markers_of(Child) == []
