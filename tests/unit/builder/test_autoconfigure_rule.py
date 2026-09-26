"""Tests for :class:`AutoconfigureRule` — nominal autoconfiguration by base type."""

from __future__ import annotations

from xtr_dependency_injection.builder.autoconfigure_rule import AutoconfigureRule


def test_add_tag_appends_one_attribute_mapping_per_call() -> None:
    class Marker:
        pass

    rule = AutoconfigureRule(type_=Marker)

    _ = rule.add_tag("kernel.reset", method="reset")
    _ = rule.add_tag("kernel.reset", method="clear")

    assert rule.tags == {"kernel.reset": [{"method": "reset"}, {"method": "clear"}]}


def test_add_tag_without_attributes_records_an_empty_mapping() -> None:
    class Marker:
        pass

    rule = AutoconfigureRule(type_=Marker).add_tag("some.tag")

    assert rule.tags == {"some.tag": [{}]}


def test_lifetime_default_is_none() -> None:
    class Marker:
        pass

    assert AutoconfigureRule(type_=Marker).lifetime is None
