from __future__ import annotations

import pytest

from xtr_dependency_injection.exception import (
    InvalidParameterTypeError,
    ParameterCircularReferenceError,
    ParameterNotFoundError,
)
from xtr_dependency_injection.parameter_bag import ParameterBag, ParameterBagInterface


def _bag() -> ParameterBag:
    return ParameterBag(
        {
            "kernel": {"project_dir": "/srv/app", "debug": True, "workers": 4},
            "app": {"log_dir": "%kernel.project_dir%/var/log", "paths": ["a"]},
        }
    )


def test_it_implements_the_interface() -> None:
    assert isinstance(ParameterBag(), ParameterBagInterface)


def test_dotted_names_read_and_write_nested_parameters() -> None:
    bag = _bag()
    bag.set("app.mailer.host", "smtp")

    assert bag.get("app.mailer") == {"host": "smtp"}
    assert bag.has("app.mailer.host")
    assert not bag.has("app.mailer.port")
    assert not bag.has("kernel.project_dir.deeper")


def test_add_merges_nested_mappings_and_replaces_leaves() -> None:
    bag = _bag()
    bag.add({"app": {"log_dir": "/var/other", "extra": {"a": 1}}})

    assert bag.get("app.log_dir") == "/var/other"
    assert bag.get("app.paths") == ["a"]
    assert bag.get("app.extra.a") == 1


def test_remove_and_clear() -> None:
    bag = _bag()
    bag.remove("app.log_dir")
    bag.remove("no.such.parameter")

    assert not bag.has("app.log_dir")
    bag.clear()
    assert bag.all() == {}


def test_an_unknown_parameter_is_refused() -> None:
    with pytest.raises(ParameterNotFoundError, match=r"app\.nope"):
        _ = _bag().get("app.nope")


def test_a_whole_reference_is_the_value_itself() -> None:
    bag = _bag()

    assert bag.resolve_string("%kernel.debug%") is True
    assert bag.resolve_string("%app.paths%") == ["a"]


def test_an_embedded_reference_must_be_a_string_or_a_number() -> None:
    bag = _bag()

    assert bag.resolve_string("%kernel.project_dir%/%kernel.workers%") == "/srv/app/4"
    with pytest.raises(InvalidParameterTypeError, match=r"kernel\.debug"):
        _ = bag.resolve_string("x%kernel.debug%")


def test_references_resolve_recursively_and_percent_stays_escaped() -> None:
    bag = _bag()
    resolved = bag.resolve_value({"dir": "%app.log_dir%", "pct": "100%%", "plain": "no refs"})

    assert resolved == {"dir": "/srv/app/var/log", "pct": "100%%", "plain": "no refs"}
    assert bag.unescape_value(resolved) == {
        "dir": "/srv/app/var/log",
        "pct": "100%",
        "plain": "no refs",
    }
    assert bag.escape_value("50%") == "50%%"


def test_a_value_without_references_is_returned_as_is() -> None:
    value = {"a": ["x"]}

    assert _bag().resolve_value(value) is value


def test_a_loop_is_refused_with_its_path() -> None:
    bag = ParameterBag({"a": "%b%", "b": "x%a%"})

    with pytest.raises(ParameterCircularReferenceError) as caught:
        _ = bag.resolve_string("%a%")

    assert caught.value.path == ("a", "b", "a")


def test_resolve_replaces_every_parameter_once() -> None:
    bag = _bag()
    bag.resolve()
    bag.resolve()

    assert bag.is_resolved()
    assert bag.get("app.log_dir") == "/srv/app/var/log"


def test_an_env_reference_needs_the_env_placeholder_bag() -> None:
    with pytest.raises(ParameterNotFoundError, match="env"):
        _ = _bag().resolve_string("%env(PORT)%")
