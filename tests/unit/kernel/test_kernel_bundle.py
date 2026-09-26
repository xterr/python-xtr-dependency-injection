from __future__ import annotations

from typing import cast

import pytest

from tests.support.bundles import EchoBundle, EchoConfig
from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.kernel import KernelInterface
from xtr_dependency_injection.kernel.kernel import Kernel
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter


def _loaded() -> BuildState:
    bundle = KernelBundle()
    state = BuildState(env="dev", debug=True, bundles=("kernel",), configs={})
    state.phase = "load"
    origin = Origin("kernel", "kernel")
    bundle.load_extension(
        NoConfig(), ServiceConfigurator(state, origin), ContainerBuilder(state, origin)
    )
    return state


def test_the_kernel_bundle_is_named_kernel() -> None:
    assert KernelBundle.metadata().name == "kernel"


def test_it_provides_the_kernel_and_the_resetter() -> None:
    state = _loaded()

    # KernelInterface is registered as an alias to the concrete _KernelInfo.
    assert (KernelInterface, None) in state.aliases
    assert state.store.get((ServicesResetter, None)) is not None


@pytest.mark.anyio
async def test_the_kernel_registers_every_config_but_no_config() -> None:
    compiled = Kernel(
        "tests.fixtures.app_kernel",
        bundles={EchoBundle: {"all": True}},
        resources=(),
        env="dev",
    ).build()

    assert isinstance(await compiled.container.get(EchoConfig), EchoConfig)
    registered = {definition.key[0] for definition in compiled.report.definitions}
    assert NoConfig not in registered


def test_the_kernel_registers_the_kernel_parameters() -> None:
    compiled = Kernel(
        "tests.fixtures.app_kernel",
        bundles={EchoBundle: {"all": True}},
        resources=(),
        env="dev",
        name="shop",
    ).build()

    assert compiled.container.get_parameter("kernel.name") == "shop"
    assert compiled.container.get_parameter("kernel.environment") == "dev"
    bundles_param = compiled.container.get_parameter("kernel.bundles")
    assert isinstance(bundles_param, dict)
    keys = cast("dict[object, object]", bundles_param).keys()
    assert "kernel" in keys
    assert "echo" in keys
