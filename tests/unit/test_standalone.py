from __future__ import annotations

from dataclasses import dataclass

import pytest
import wireup

from tests.fixtures.app_kernel_late import LateService
from tests.support.bundles import ChorusBundle, EchoBundle, EchoConfig
from xtr_dependency_injection import Bundle, as_bundle, injectables
from xtr_dependency_injection.exception import (
    ConfigProviderError,
    MissingBundleError,
    UnknownConfigTypeError,
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


async def test_the_injectables_build_a_working_container() -> None:
    container = wireup.create_async_container(injectables=injectables([QuietBundle()]))

    info = await container.get(KernelInterface)

    assert (info.name, info.environment, info.debug) == ("standalone", "prod", False)
    assert info.bundles == ("kernel", "quiet")
    assert [report.name for report in info.report.bundles] == ["kernel", "quiet"]


async def test_a_given_config_is_the_bundles_base() -> None:
    container = wireup.create_async_container(
        injectables=injectables([TunedBundle()], configs=[TunedConfig(level=7)])
    )

    assert await container.get(TunedConfig) == TunedConfig(level=7)


async def test_without_a_given_config_the_default_is_used() -> None:
    container = wireup.create_async_container(injectables=injectables([TunedBundle()]))

    assert await container.get(TunedConfig) == TunedConfig()


def test_a_missing_requirement_is_not_discovered() -> None:
    with pytest.raises(MissingBundleError) as caught:
        _ = injectables([ChorusBundle()])

    assert (caught.value.name, caught.value.required_by) == ("echo", "chorus")


def test_a_config_no_listed_bundle_declares_is_refused() -> None:
    with pytest.raises(UnknownConfigTypeError):
        _ = injectables([QuietBundle()], configs=[EchoConfig()])


def test_parameters_from_a_bundle_need_the_kernel() -> None:
    with pytest.raises(ConfigProviderError, match="parameters need the kernel") as caught:
        _ = injectables([EchoBundle()])

    assert caught.value.provider == "bundle echo"


def test_parameters_from_a_scanned_provider_need_the_kernel() -> None:
    with pytest.raises(ConfigProviderError, match="provided"):
        _ = injectables([QuietBundle()], scan=["tests.fixtures.app_parameters"])


async def test_scanned_resources_are_registered_as_the_applications() -> None:
    emitted = injectables([QuietBundle()], scan=["tests.fixtures.app_kernel_late"])
    container = wireup.create_async_container(injectables=emitted)

    assert isinstance(await container.get(LateService), LateService)
