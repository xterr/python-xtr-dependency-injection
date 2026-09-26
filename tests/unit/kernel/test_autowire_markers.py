"""End-to-end: ``Autowire``, ``Target`` and ``Injected`` drive real injection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import pytest
import wireup
from typing_extensions import override

from xtr_dependency_injection import Autowire, Bundle, Kernel, Target, as_bundle
from xtr_dependency_injection.kernel.booted_kernel import call_injected
from xtr_dependency_injection.runtime import bind_callable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator
    from xtr_dependency_injection.bundle.bundle import AnyBundle

pytestmark = pytest.mark.anyio

APP = "tests.fixtures.app_empty"


class Mailer:
    def __init__(self, label: str) -> None:
        self.label: str = label


class Envelope:
    def __init__(self, env_name: Annotated[str, Autowire(param="kernel.environment")]) -> None:
        self.env_name: str = env_name


class Picky:
    def __init__(self, mailer: Annotated[Mailer, Target("smtp")]) -> None:
        self.mailer: Mailer = mailer


class ForwardRefEnvelope:
    def __init__(
        self,
        env_name: Annotated["str", Autowire(param="kernel.environment")],  # noqa: UP037
    ) -> None:
        self.env_name: str = env_name


class ForwardRefPicky:
    def __init__(self, mailer: Annotated["Mailer", Target("smtp")]) -> None:  # noqa: UP037
        self.mailer: Mailer = mailer


def _smtp() -> Mailer:
    return Mailer("smtp")


def _http() -> Mailer:
    return Mailer("http")


@as_bundle("markers")
class MarkerBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        _ = services.set(Envelope)
        _ = services.set(Picky)
        _ = services.set(ForwardRefEnvelope)
        _ = services.set(ForwardRefPicky)
        _ = services.set(_smtp, qualifier="smtp")
        _ = services.set(_http, qualifier="http")


_BUNDLES: dict[type[AnyBundle], Mapping[str, bool]] = {  # type: ignore[misc]
    MarkerBundle: {"all": True},
}


def _kernel() -> Kernel:
    return Kernel(APP, env="dev", name="shop", bundles=_BUNDLES)


async def test_autowire_param_pulls_a_kernel_parameter_into_a_constructor() -> None:
    compiled = _kernel().build()

    envelope = await compiled.container.get(Envelope)

    assert envelope.env_name == "dev"


async def test_target_selects_a_qualifier_on_a_constructor() -> None:
    compiled = _kernel().build()

    picky = await compiled.container.get(Picky)

    assert picky.mailer.label == "smtp"


async def test_a_string_nested_in_annotated_autowire_param_resolves() -> None:
    compiled = _kernel().build()

    envelope = await compiled.container.get(ForwardRefEnvelope)

    assert envelope.env_name == "dev"


async def test_a_string_nested_in_annotated_target_resolves() -> None:
    compiled = _kernel().build()

    picky = await compiled.container.get(ForwardRefPicky)

    assert picky.mailer.label == "smtp"


async def test_injected_marks_a_hook_parameter_reached_through_call_injected() -> None:
    async def targeted(mailer: Annotated[Mailer, Target("http")]) -> str:
        return mailer.label

    booted = await _kernel().boot()
    try:
        result = await call_injected(booted._engine, targeted)

        assert result == "http"
    finally:
        await booted.shutdown()


async def test_bind_callable_fills_an_injected_parameter() -> None:
    async def send_smtp(mailer: Annotated[Mailer, Target("smtp")]) -> str:
        return mailer.label

    booted = await _kernel().boot()
    try:
        bound_smtp = bind_callable(booted.container, send_smtp)
        result = await bound_smtp()

        assert result == "smtp"
    finally:
        await booted.shutdown()


async def test_wireup_inject_written_by_user_code_still_resolves() -> None:
    class WireupUser:
        def __init__(
            self, env_name: Annotated[str, wireup.Inject(config="kernel.environment")]
        ) -> None:
            self.env_name: str = env_name

    @as_bundle("interop")
    class InteropBundle(Bundle):
        @override
        def load_extension(
            self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
        ) -> None:
            _ = services.set(WireupUser)

    compiled = Kernel(
        APP,
        env="dev",
        name="shop",
        bundles={InteropBundle: {"all": True}},
    ).build()

    user = await compiled.container.get(WireupUser)

    assert user.env_name == "dev"
