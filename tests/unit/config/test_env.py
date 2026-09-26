from __future__ import annotations

import pytest

from xtr_dependency_injection.config import env
from xtr_dependency_injection.exception import (
    InvalidEnvironmentVariableError,
    MissingEnvironmentVariableError,
)


def test_a_set_variable_is_read_as_a_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_TEST_DSN", "sync://")

    assert env("XTR_TEST_DSN") == "sync://"


def test_a_variable_is_converted_by_cast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_TEST_PORT", "8080")

    assert env("XTR_TEST_PORT", int) == 8080


def test_an_unset_variable_returns_the_default_unconverted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XTR_TEST_PORT", raising=False)

    assert env("XTR_TEST_PORT", int, default=None) is None


def test_an_unset_variable_without_default_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XTR_TEST_DSN", raising=False)

    with pytest.raises(MissingEnvironmentVariableError):
        _ = env("XTR_TEST_DSN")


def test_a_value_the_cast_refuses_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_TEST_PORT", "eighty")

    with pytest.raises(InvalidEnvironmentVariableError) as caught:
        _ = env("XTR_TEST_PORT", int)

    assert isinstance(caught.value.__cause__, ValueError)


@pytest.mark.parametrize("raw", ["1", "true", "YES", "On"])
def test_bool_reads_truthy_words(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("XTR_TEST_FLAG", raw)

    assert env("XTR_TEST_FLAG", bool) is True


@pytest.mark.parametrize("raw", ["0", "false", "No", "OFF", ""])
def test_bool_reads_falsy_words(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("XTR_TEST_FLAG", raw)

    assert env("XTR_TEST_FLAG", bool) is False


def test_bool_refuses_anything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XTR_TEST_FLAG", "maybe")

    with pytest.raises(InvalidEnvironmentVariableError):
        _ = env("XTR_TEST_FLAG", bool)


def test_string_default_yields_a_str_or_none_typed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """The typed assignment below is what basedpyright validates for todo 24."""
    monkeypatch.delenv("XTR_TEST_MISSING", raising=False)

    value: str | None = env("XTR_TEST_MISSING", default=None)

    assert value is None


def test_cast_default_yields_a_typed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XTR_TEST_MISSING", raising=False)

    value: int | None = env("XTR_TEST_MISSING", int, default=None)

    assert value is None
