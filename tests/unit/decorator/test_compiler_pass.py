from __future__ import annotations

from xtr_dependency_injection.decorator.compiler_pass import (
    CompilerPassMarker,
    compiler_pass,
    compiler_pass_of,
)


def test_a_bare_compiler_pass_has_priority_zero() -> None:
    @compiler_pass
    def adjust(_builder: object) -> None: ...

    assert compiler_pass_of(adjust) == CompilerPassMarker(0)


def test_a_compiler_pass_records_its_priority() -> None:
    @compiler_pass(priority=5)
    def adjust(_builder: object) -> None: ...

    assert compiler_pass_of(adjust) == CompilerPassMarker(5)


def test_an_unmarked_function_is_not_a_compiler_pass() -> None:
    def adjust(_builder: object) -> None: ...

    assert compiler_pass_of(adjust) is None
