from __future__ import annotations

from dataclasses import dataclass

import pytest
import wireup

from tests.fixtures.app_env import MailBundle, Mailer, PortReader
from tests.fixtures.app_kernel_late import LateService
from tests.support.bundles import EchoBundle, EchoConfig
from xtr_dependency_injection import Bundle, Kernel, as_bundle, required_bundle
from xtr_dependency_injection.exception import (
    ConfigProviderError,
    MissingBundleError,
    ParameterConflictError,
    UnknownConfigTypeError,
)
from xtr_dependency_injection.integration.wireup import (
    create_container,
    engine_container,
    injectables,
)
from xtr_dependency_injection.kernel import KernelInterface

pytestmark = pytest.mark.anyio


@dataclass(frozen=True)
class TunedConfig:
    level: int = 1


@as_bundle("quiet")
class QuietBundle(Bundle):
    pass


@as_bundle("tuned", config=TunedConfig)
class TunedBundle(Bundle[TunedConfig]):
    pass


@required_bundle("nowhere_installed:MissingBundle")
@as_bundle("needs_missing")
class NeedsMissingBundle(Bundle):
    pass


async def test_the_injectables_build_a_working_container() -> None:
    container = wireup.create_async_container(injectables=injectables([QuietBundle]))

    info = await container.get(KernelInterface)

    assert (info.name, info.environment, info.debug) == ("standalone", "prod", False)
    assert info.bundles == ("kernel", "quiet")
    assert [report.name for report in info.report.bundles] == ["kernel", "quiet"]


async def test_a_given_config_is_the_bundles_base() -> None:
    container = wireup.create_async_container(
        injectables=injectables([TunedBundle], configs=[TunedConfig(level=7)])
    )

    assert await container.get(TunedConfig) == TunedConfig(level=7)


async def test_without_a_given_config_the_default_is_used() -> None:
    container = wireup.create_async_container(injectables=injectables([TunedBundle]))

    assert await container.get(TunedConfig) == TunedConfig()


def test_a_missing_required_string_is_refused() -> None:
    with pytest.raises(MissingBundleError) as caught:
        _ = injectables([NeedsMissingBundle])

    assert caught.value.name == "nowhere_installed:MissingBundle"
    assert caught.value.required_by == "needs_missing"


def test_a_config_no_listed_bundle_declares_is_refused() -> None:
    with pytest.raises(UnknownConfigTypeError):
        _ = injectables([QuietBundle], configs=[EchoConfig()])


def test_parameters_from_a_bundle_need_create_container() -> None:
    with pytest.raises(ConfigProviderError, match="parameters need create_container") as caught:
        _ = injectables([EchoBundle])

    assert caught.value.provider == "bundle echo"


def test_parameters_from_a_scanned_provider_need_the_kernel() -> None:
    with pytest.raises(ConfigProviderError, match="provided"):
        _ = injectables([QuietBundle], scan=["tests.fixtures.app_parameters"])


async def test_scanned_resources_are_registered_as_the_applications() -> None:
    emitted = injectables([QuietBundle], scan=["tests.fixtures.app_kernel_late"])
    container = wireup.create_async_container(injectables=emitted)

    assert isinstance(await container.get(LateService), LateService)


def test_engine_container_returns_the_wireup_container_from_a_compiled_kernel() -> None:
    compiled = Kernel("json", resources=(), bundles={}).build()

    engine = engine_container(compiled)

    assert isinstance(engine, wireup.AsyncContainer)


async def test_engine_container_returns_the_wireup_container_from_a_booted_kernel() -> None:
    booted = await Kernel("json", resources=(), bundles={}).boot()
    try:
        engine = engine_container(booted)

        assert isinstance(engine, wireup.AsyncContainer)
    finally:
        await booted.shutdown()


def test_engine_container_refuses_a_foreign_kernel() -> None:
    with pytest.raises(TypeError, match="CompiledKernel or BootedKernel"):
        _ = engine_container(object())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]


async def test_create_container_carries_every_parameter() -> None:
    container = create_container(
        [EchoBundle],
        scan=["tests.fixtures.app_parameters"],
        parameters={"own": {"flag": True}},
    )

    assert container.config.get("echo.greeting") == EchoConfig().greeting
    assert container.config.get("app.name") == "fixture"
    assert container.config.get("own.flag") is True
    assert container.config.get("kernel.name") == "standalone"


async def test_create_container_resolves_environment_variables() -> None:
    container = create_container(
        [MailBundle],
        scan=["tests.fixtures.app_env"],
        environ={"MAIL_HOST": "mx", "MAIL_PORT": "2525", "MAIL_USER": "u", "MAIL_WORKERS": "2"},
    )

    reader = await container.get(PortReader)
    mailer = await container.get(Mailer)

    assert reader.port == 2525
    assert (mailer.config.host, mailer.config.port, mailer.config.user) == ("mx", 2525, "u")


def test_create_container_refuses_a_parameter_set_twice() -> None:
    with pytest.raises(ParameterConflictError):
        _ = create_container([EchoBundle], parameters={"echo": {"greeting": "again"}})
