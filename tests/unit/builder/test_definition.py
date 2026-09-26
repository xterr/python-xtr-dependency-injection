from __future__ import annotations

from xtr_dependency_injection.builder import Definition, Origin


class Sample:
    pass


def test_an_origin_reads_as_kind_and_name() -> None:
    assert str(Origin("bundle", "logging")) == "bundle logging"


def test_an_origin_note_is_shown_in_parentheses() -> None:
    origin = Origin("bundle", "console", "via autoconfigure of app.x:Y")

    assert str(origin) == "bundle console (via autoconfigure of app.x:Y)"


def test_a_definition_defaults_to_no_priority_and_no_decoration() -> None:
    definition = Definition(
        key=(Sample, None),
        provider=Sample,
        kind="class",
        lifetime="singleton",
        origin=Origin("app", "tests:Sample"),
    )

    assert definition.priority is None
    assert (definition.tags, definition.decorates) == ({}, None)
    assert (definition.before, definition.after) == ((), ())
