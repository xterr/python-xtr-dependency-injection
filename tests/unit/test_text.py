from __future__ import annotations

from typing_extensions import override

from xtr_dependency_injection._text import safe_repr, safe_str


class _UnprintableError(Exception):
    @override
    def __str__(self) -> str:
        raise ValueError("cannot say")

    @override
    def __repr__(self) -> str:
        raise ValueError("cannot say")


def test_safe_str_returns_what_the_error_says() -> None:
    assert safe_str(ValueError("boom")) == "boom"


def test_safe_str_names_an_unprintable_error_by_its_class() -> None:
    assert safe_str(_UnprintableError()) == f"[unprintable {__name__}._UnprintableError]"


def test_safe_repr_returns_the_errors_repr() -> None:
    assert safe_repr(ValueError("boom")) == "ValueError('boom')"


def test_safe_repr_names_an_unprintable_error_by_its_class() -> None:
    assert safe_repr(_UnprintableError()) == f"[unprintable {__name__}._UnprintableError]"
