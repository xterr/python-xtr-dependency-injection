from __future__ import annotations

from xtr_dependency_injection.decorator.as_service import ServiceMarker, as_service, service_of


class Plain:
    pass


def test_service_of_returns_none_when_the_class_is_not_marked() -> None:
    assert service_of(Plain) is None


def test_as_service_records_its_defaults_on_a_class() -> None:
    @as_service()
    class Marked:
        pass

    marker = service_of(Marked)

    assert marker == ServiceMarker(lifetime="singleton", qualifier=None)


def test_as_service_records_a_custom_lifetime_and_qualifier() -> None:
    @as_service(lifetime="transient", qualifier="fast")
    class Marked:
        pass

    marker = service_of(Marked)

    assert marker == ServiceMarker(lifetime="transient", qualifier="fast")


def test_as_service_marks_a_factory_function() -> None:
    @as_service(lifetime="scoped")
    def build() -> Plain:
        return Plain()

    marker = service_of(build)

    assert marker == ServiceMarker(lifetime="scoped", qualifier=None)


def test_a_subclass_does_not_inherit_the_marker() -> None:
    @as_service()
    class Parent:
        pass

    class Child(Parent):
        pass

    assert service_of(Child) is None


def test_as_service_bare_form_on_a_class() -> None:
    @as_service
    class Marked:
        pass

    marker = service_of(Marked)

    assert marker == ServiceMarker(lifetime="singleton", qualifier=None)


def test_as_service_bare_form_on_a_factory_function() -> None:
    @as_service
    def build() -> Plain:
        return Plain()

    marker = service_of(build)

    assert marker == ServiceMarker(lifetime="singleton", qualifier=None)
