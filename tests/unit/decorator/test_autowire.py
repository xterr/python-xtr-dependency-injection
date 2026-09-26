"""``Autowire``, ``Target`` and ``Injected`` compile down to wireup's markers."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Annotated, cast, get_args, get_origin

import pytest
import wireup
from wireup.ioc.types import (
    ConfigInjectionRequest,
    EmptyContainerInjectionRequest,
    InjectableQualifier,
)

from xtr_dependency_injection.compiler._wireup_bridge import to_engine_signature
from xtr_dependency_injection.decorator.autowire import Autowire, Injected, Target

if TYPE_CHECKING:
    from collections.abc import Callable


def _annotations(signature: inspect.Signature) -> dict[str, object]:
    return {name: cast("object", param.annotation) for name, param in signature.parameters.items()}


def _metadata(annotation: object) -> tuple[object, ...]:
    assert get_origin(annotation) is Annotated
    parts = cast("tuple[object, ...]", get_args(annotation))
    return parts[1:]


def _rewritten_metadata(target: object, name: str) -> tuple[object, ...]:
    signature = inspect.signature(cast("Callable[..., object]", target), eval_str=True)
    rewritten = to_engine_signature(signature)
    return _metadata(_annotations(rewritten)[name])


def _echo(value: object) -> object:
    return value


def test_injected_is_annotated_with_a_plain_autowire() -> None:
    metadata = _metadata(Injected[int])
    assert metadata == (Autowire(),)


def test_autowire_param_becomes_wireup_inject_config() -> None:
    def target(value: Annotated[str, Autowire(param="kernel.name")]) -> object:
        return _echo(value)

    metadata = _rewritten_metadata(target, "value")

    assert isinstance(metadata[0], ConfigInjectionRequest)
    assert metadata[0].config_key == "kernel.name"


def test_target_becomes_wireup_inject_qualifier() -> None:
    def target(mailer: Annotated[object, Target("smtp")]) -> object:
        return _echo(mailer)

    metadata = _rewritten_metadata(target, "mailer")

    assert isinstance(metadata[0], InjectableQualifier)
    assert metadata[0].qualifier == "smtp"


def test_injected_becomes_wireup_empty_inject() -> None:
    def target(value: Injected[int]) -> object:
        return _echo(value)

    metadata = _rewritten_metadata(target, "value")

    assert isinstance(metadata[0], EmptyContainerInjectionRequest)


def test_a_signature_without_our_markers_is_returned_unchanged() -> None:
    def target(value: int, other: Annotated[str, "meta"]) -> tuple[int, str]:
        return value, other

    signature = inspect.signature(cast("Callable[..., object]", target), eval_str=True)
    assert to_engine_signature(signature) is signature


def test_wireup_inject_written_by_a_user_passes_through_untouched() -> None:
    def target(url: Annotated[str, wireup.Inject(config="db.url")]) -> object:
        return _echo(url)

    metadata = _rewritten_metadata(target, "url")

    assert isinstance(metadata[0], ConfigInjectionRequest)
    assert metadata[0].config_key == "db.url"


def test_unrelated_metadata_is_preserved_alongside_a_translated_marker() -> None:
    def target(value: Annotated[int, "sentinel", Autowire(param="kernel.debug")]) -> object:
        return _echo(value)

    metadata = _rewritten_metadata(target, "value")

    assert metadata[0] == "sentinel"
    assert isinstance(metadata[1], ConfigInjectionRequest)


def test_autowire_and_target_are_hashable_frozen_dataclasses() -> None:
    assert Autowire() == Autowire()
    assert Autowire(param="x") == Autowire(param="x")
    assert Target("smtp") == Target("smtp")
    assert Target("smtp") != Target("http")
    _ = {Autowire(), Target("smtp")}


def test_target_requires_a_name() -> None:
    with pytest.raises(TypeError):
        # Runtime call — the missing argument is what this test proves.
        _ = cast("Callable[[], Target]", Target)()
