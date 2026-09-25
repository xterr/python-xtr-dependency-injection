from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

from tests.fixtures.app_kernel.services import Greeter
from tests.support.bundles import EVENTS, ChorusBundle, Echo, EchoBundle, EchoConfig
from xtr_dependency_injection import Bundle, Kernel, as_bundle
from xtr_dependency_injection.testing import assert_zero_config, boot_for_test

if TYPE_CHECKING:
    from wireup import AsyncContainer

    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator

pytestmark = pytest.mark.anyio


class FakeEcho(Echo):
    @override
    def say(self) -> str:
        return "fake"


@dataclass(frozen=True)
class StrictConfig:
    dsn: str = ""


@as_bundle("strict", config=StrictConfig)
class StrictBundle(Bundle[StrictConfig]):
    @override
    def load(self, config: StrictConfig, services: ServiceConfigurator) -> None:
        if not config.dsn:
            msg = "strict needs a dsn"
            raise ValueError(msg)


@as_bundle("booting")
class BootingBundle(Bundle):
    @override
    async def boot(self, container: AsyncContainer) -> None:
        EVENTS.append("boot:booting")


def _kernel() -> Kernel:
    return Kernel("tests.fixtures.app_kernel", bundles=[EchoBundle(), ChorusBundle()])


async def test_boot_for_test_builds_for_the_test_environment() -> None:
    async with await boot_for_test(_kernel()) as booted:
        assert booted.kernel.environment == "test"


async def test_overrides_are_active_before_boot_hooks_run() -> None:
    EVENTS.clear()

    async with await boot_for_test(_kernel(), overrides={Echo: FakeEcho(EchoConfig())}) as booted:
        greeter = await booted.container.get(Greeter)

    assert greeter.greet() == "fake!"
    assert "boot:app fake!" in EVENTS


async def test_a_qualified_override_uses_a_tuple_key() -> None:
    fake = FakeEcho(EchoConfig())

    async with await boot_for_test(_kernel(), overrides={(Echo, None): fake}) as booted:
        assert await booted.container.get(Echo) is fake


async def test_a_zero_config_bundle_passes() -> None:
    EVENTS.clear()

    await assert_zero_config(BootingBundle)

    assert EVENTS == ["boot:booting"]


async def test_a_bundle_needing_configuration_fails() -> None:
    with pytest.raises(ValueError, match="needs a dsn"):
        await assert_zero_config(StrictBundle)
