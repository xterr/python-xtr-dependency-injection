from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.config import env
from xtr_dependency_injection.config.env_placeholder import EnvPlaceholder
from xtr_dependency_injection.exception import (
    InvalidEnvironmentVariableError,
    MissingEnvironmentVariableError,
)
from xtr_dependency_injection.runtime.env_var_processor import EnvVarProcessor
from xtr_dependency_injection.runtime.env_var_processors_locator import EnvVarProcessorsLocator

if TYPE_CHECKING:
    from collections.abc import Callable


class Suit(Enum):
    HEARTS = "hearts"


def _read(value: object, **environ: str) -> object:
    assert isinstance(value, EnvPlaceholder)
    processor = EnvVarProcessor(environ)
    locator = EnvVarProcessorsLocator(dict.fromkeys(processor.get_provided_types(), processor))
    return value.resolve(locator.get_env)


def test_env_returns_a_placeholder_not_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_TEST_DSN", "sync://")

    placeholder = env("XTR_TEST_DSN")

    assert isinstance(placeholder, EnvPlaceholder)
    assert repr(placeholder) == "env(XTR_TEST_DSN)"
    assert placeholder != "sync://"


def test_a_placeholder_resolves_to_the_variable() -> None:
    assert _read(env("DSN"), DSN="sync://") == "sync://"


@pytest.mark.parametrize(
    ("converter", "expression", "value", "expected"),
    [
        (int, "int:PORT", "8080", 8080),
        (float, "float:PORT", "1.5", 1.5),
        (bool, "bool:PORT", "yes", True),
        (str, "PORT", "80", "80"),
        (Suit, f"enum:{__name__}.Suit:PORT", "hearts", Suit.HEARTS),
    ],
    ids=["int", "float", "bool", "str", "enum"],
)
def test_a_cast_becomes_the_prefix_it_stands_for(
    converter: Callable[[str], object], expression: str, value: str, expected: object
) -> None:
    placeholder = env("PORT", converter)

    assert isinstance(placeholder, EnvPlaceholder)
    assert placeholder.expression == expression
    assert _read(placeholder, PORT=value) == expected


def test_a_prefix_chain_is_kept_as_written() -> None:
    placeholder = env("json:SETTINGS")

    assert isinstance(placeholder, EnvPlaceholder)
    assert placeholder.expression == "json:SETTINGS"
    assert _read(placeholder, SETTINGS='{"a": 1}') == {"a": 1}


def test_any_other_callable_is_applied_to_the_value() -> None:
    def upper(value: str) -> str:
        return value.upper()

    placeholder = env("NAME", upper)

    assert _read(placeholder, NAME="acme") == "ACME"


def test_an_unset_variable_returns_the_default_unconverted() -> None:
    assert _read(env("PORT", int, default=None)) is None


def test_the_default_is_what_a_numeric_placeholder_holds_while_building() -> None:
    placeholder = env("PORT", int, default=8080)

    assert isinstance(placeholder, int)
    assert placeholder + 0 == 8080


def test_an_unset_variable_without_default_is_refused() -> None:
    with pytest.raises(MissingEnvironmentVariableError, match="PORT"):
        _ = _read(env("PORT", int))


def test_a_value_the_cast_refuses_is_refused() -> None:
    with pytest.raises(InvalidEnvironmentVariableError, match="PORT"):
        _ = _read(env("PORT", int), PORT="eighty")


def test_a_callable_refusing_the_value_is_refused() -> None:
    def strict(value: str) -> int:
        return int(value)

    with pytest.raises(InvalidEnvironmentVariableError, match="NAME"):
        _ = _read(env("NAME", strict), NAME="x")
