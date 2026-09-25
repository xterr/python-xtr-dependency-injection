from __future__ import annotations

from xtr_dependency_injection.decorator.exclude import exclude, is_excluded


def test_exclude_marks_the_object() -> None:
    @exclude
    class Helper:
        pass

    assert is_excluded(Helper)


def test_an_unmarked_object_is_not_excluded() -> None:
    class Helper:
        pass

    assert not is_excluded(Helper)


def test_a_subclass_of_an_excluded_class_is_not_excluded() -> None:
    @exclude
    class Base:
        pass

    class Concrete(Base):
        pass

    assert not is_excluded(Concrete)
