"""The markers double as the web framework's dependency declarations when it is installed."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI
from fastapi.params import Depends

from xtr_dependency_injection import Autowire, Injected, Target
from xtr_dependency_injection.decorator import _dependency_base
from xtr_dependency_injection.decorator._dependency_base import set_dependency
from xtr_dependency_injection.integration import _resolvers
from xtr_dependency_injection.integration.fastapi import provider

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class Greeter:
    """What a route asks for, resolved through the container."""

    def greet(self) -> str:
        return "hello"


def _as_dependency(marker: object) -> Depends:
    assert isinstance(marker, Depends)
    return marker


def test_the_framework_shape_is_active_in_this_suite() -> None:
    assert _dependency_base.IS_DEPENDENCY is True
    assert _dependency_base.DependencyBase is Depends


def test_the_markers_are_framework_dependencies() -> None:
    assert isinstance(Autowire(), Depends)
    assert isinstance(Target("a"), Depends)


def test_a_bare_autowire_keeps_no_resolver() -> None:
    marker = _as_dependency(Autowire())

    assert marker.dependency is None
    assert marker.use_cache is True
    assert marker.scope is None


def test_a_bare_target_keeps_no_resolver() -> None:
    assert _as_dependency(Target("smtp")).dependency is None


def test_the_framework_copy_of_a_bare_autowire_resolves_a_service() -> None:
    copied = _as_dependency(dataclasses.replace(Autowire(), dependency=Greeter))

    assert copied.dependency is provider("service", Greeter, None)


def test_the_framework_copy_of_a_target_carries_its_qualifier() -> None:
    copied = dataclasses.replace(Target("a"), dependency=Greeter)

    assert copied.name == "a"
    assert _as_dependency(copied).dependency is provider("service", Greeter, "a")


def test_a_parameter_marker_resolves_through_the_parameter_provider() -> None:
    marker = _as_dependency(Autowire(param="kernel.name"))

    assert marker.dependency is provider("param", "kernel.name")


def test_a_variable_marker_resolves_through_the_environment_provider() -> None:
    marker = _as_dependency(Autowire(env="int:PORT"))

    assert marker.dependency is provider("env", "int:PORT")


def test_copying_an_already_derived_marker_keeps_its_resolver() -> None:
    marker = Autowire(param="kernel.name")

    copied = _as_dependency(dataclasses.replace(marker, scope="request"))

    assert copied.dependency is provider("param", "kernel.name")
    assert copied.scope == "request"


def test_equal_markers_carry_the_same_resolver() -> None:
    assert Autowire(param="kernel.name") == Autowire(param="kernel.name")
    assert Autowire(env="PORT") == Autowire(env="PORT")
    assert Autowire(param="kernel.name") != Autowire(env="PORT")


def test_arguments_the_framework_copy_never_passes_are_refused() -> None:
    with pytest.raises(TypeError, match="unexpected arguments: colour"):
        _ = Autowire(colour="blue")


def test_without_the_framework_extra_arguments_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_dependency_base, "IS_DEPENDENCY", False)

    with pytest.raises(TypeError, match="unexpected arguments: dependency, use_cache"):
        set_dependency(object(), {"use_cache": False, "dependency": None})


def test_without_the_framework_a_marker_needs_nothing_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_dependency_base, "IS_DEPENDENCY", False)

    # ``object()`` refuses every attribute write: returning without one is the proof.
    set_dependency(object(), {})


@pytest.mark.anyio
async def test_a_route_declaring_a_bare_marker_learns_which_service_it_stands_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The framework's route analysis copies a bare marker with the parameter's type.

    Pinned as behaviour — a request through a real application — rather than
    by reading the framework's source, so it must keep holding on every
    supported framework version.
    """
    seen: list[tuple[str, object, object]] = []
    served = Greeter()

    def fake_provider(
        kind: str,
        key: object,
        qualifier: object = None,
    ) -> Callable[[], Awaitable[object]]:
        seen.append((kind, key, qualifier))

        async def resolve() -> object:
            return served

        return resolve

    monkeypatch.setattr(_resolvers, "provider", fake_provider)
    app = FastAPI()

    @app.get("/greeting")
    async def greeting(greeter: Injected[Greeter]) -> dict[str, str]:
        return {"greeting": greeter.greet()}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/greeting")

    assert response.status_code == 200
    assert response.json() == {"greeting": "hello"}
    assert ("service", Greeter, None) in seen
