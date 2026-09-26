"""Tests for ``@autoconfigure`` and ``@autoconfigure_tag``."""

from __future__ import annotations

from xtr_dependency_injection.decorator.autoconfigure import (
    autoconfigure,
    autoconfigure_of,
    autoconfigure_tag,
    autoconfigure_tags_of,
)


def test_autoconfigure_records_tags_lifetime_and_factory() -> None:
    def factory() -> object:
        return object()

    @autoconfigure(tags=("t1", ("t2", {"a": 1})), lifetime="scoped", factory=factory)
    class Marker:
        pass

    marker = autoconfigure_of(Marker)

    assert marker is not None
    assert marker.tags == ("t1", ("t2", {"a": 1}))
    assert marker.lifetime == "scoped"
    assert marker.factory is factory


def test_autoconfigure_of_returns_none_when_absent() -> None:
    class Bare:
        pass

    assert autoconfigure_of(Bare) is None


def test_autoconfigure_tag_default_name_stays_none_on_the_marker() -> None:
    @autoconfigure_tag()
    class Marker:
        pass

    (only,) = autoconfigure_tags_of(Marker)

    # The kernel derives the default from ``qualified_name(cls)`` at apply
    # time; the marker itself records ``None``.
    assert only.name is None
    assert only.attributes == {}


def test_autoconfigure_tag_is_repeatable() -> None:
    @autoconfigure_tag("first", priority=1)
    @autoconfigure_tag("second", priority=2)
    class Marker:
        pass

    tags = autoconfigure_tags_of(Marker)

    # Decoration is bottom-up: ``second`` is applied first, then ``first``.
    assert [t.name for t in tags] == ["second", "first"]
    assert [dict(t.attributes) for t in tags] == [{"priority": 2}, {"priority": 1}]


def test_a_subclass_does_not_inherit_the_marker() -> None:
    @autoconfigure(tags=("t",))
    class Base:
        pass

    class Sub(Base):
        pass

    assert autoconfigure_of(Sub) is None
