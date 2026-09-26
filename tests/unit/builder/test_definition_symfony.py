from __future__ import annotations

from xtr_dependency_injection.builder import Decorates, Definition, Origin


class Mailer:
    pass


class Iface:
    pass


def _make() -> Definition:
    return Definition(
        key=(Mailer, None),
        provider=Mailer,
        kind="class",
        lifetime="singleton",
        origin=Origin("app", "tests:Mailer"),
    )


def test_add_tag_records_attributes_repeatably() -> None:
    definition = _make()

    _ = definition.add_tag("kernel.reset", method="reset")
    _ = definition.add_tag("kernel.reset", method="clear")

    assert definition.has_tag("kernel.reset")
    assert definition.get_tag("kernel.reset") == [{"method": "reset"}, {"method": "clear"}]


def test_get_tag_returns_empty_for_a_missing_tag() -> None:
    definition = _make()

    assert not definition.has_tag("nope")
    assert definition.get_tag("nope") == []


def test_clear_tag_forgets_a_tag() -> None:
    definition = _make()
    _ = definition.add_tag("x", value=1)

    _ = definition.clear_tag("x")

    assert not definition.has_tag("x")


def test_set_decorated_service_records_a_decorates_record() -> None:
    definition = _make()

    _ = definition.set_decorated_service(Iface, qualifier="q", priority=5)

    assert definition.decorates == Decorates(key=(Iface, "q"), priority=5)


def test_new_fields_default_to_empty() -> None:
    definition = _make()

    assert definition.tags == {}
    assert definition.decorates is None
    assert definition.before == ()
    assert definition.after == ()
    assert definition.priority is None
