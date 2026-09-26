"""Regression: a string nested in ``Annotated[...]`` is evaluated, not left a ForwardRef.

``inspect.signature(eval_str=True)`` resolves a top-level string annotation but
leaves a string *inside* ``Annotated[...]`` a ``ForwardRef``;
:func:`evaluated_signature` resolves it through ``typing.get_type_hints``. Before
that fix the container failed to compile on ``Annotated["Dep", Target("x")]``
("unknown dependency on ForwardRef('Dep')") and a decorator's
``Annotated["Mailer | None", AutowireDecorated()]`` was rejected.
"""

from __future__ import annotations

import inspect
import typing
from typing import TYPE_CHECKING, Annotated, cast

import pytest

from xtr_dependency_injection import Autowire, Target
from xtr_dependency_injection.exception._naming import ANNOTATION_HINT
from xtr_dependency_injection.exception._signatures import evaluated_signature

if TYPE_CHECKING:

    class Nope:
        pass


class Dep:
    pass


def _ctor(dep: Annotated["Dep", Target("x")]) -> None:  # noqa: UP037
    del dep


class Service:
    def __init__(self, dep: Annotated["Dep", Autowire(param="kernel.name")]) -> None:  # noqa: UP037
        self.dep: Dep = dep


def _args_of(signature: inspect.Signature, name: str) -> tuple[object, ...]:
    annotation = cast("object", signature.parameters[name].annotation)
    return cast("tuple[object, ...]", typing.get_args(annotation))


def test_the_raw_eval_str_signature_leaks_a_forward_ref() -> None:
    raw = inspect.signature(_ctor, eval_str=True)

    wrapped, _marker = _args_of(raw, "dep")

    assert isinstance(wrapped, typing.ForwardRef)


def test_a_string_nested_in_annotated_on_a_function_is_resolved() -> None:
    signature = evaluated_signature(_ctor)

    wrapped, marker = _args_of(signature, "dep")

    assert wrapped is Dep
    assert marker == Target("x")


def test_a_string_nested_in_annotated_on_a_class_init_is_resolved() -> None:
    signature = evaluated_signature(Service)

    wrapped, marker = _args_of(signature, "dep")

    assert wrapped is Dep
    assert marker == Autowire(param="kernel.name")


def test_a_pre_set_signature_is_honored_verbatim() -> None:
    def synthesized() -> None: ...

    presented = inspect.Signature(parameters=[], return_annotation=Dep)
    setattr(synthesized, "__signature__", presented)  # noqa: B010

    assert evaluated_signature(synthesized) == presented


def test_an_unresolvable_annotation_notes_the_hint_with_context() -> None:
    def bad(dep: Nope) -> None:
        del dep

    with pytest.raises(NameError) as caught:
        _ = evaluated_signature(bad, context="reading it")

    notes = caught.value.__notes__
    assert any(ANNOTATION_HINT in note for note in notes)
    assert any("reading it" in note for note in notes)
