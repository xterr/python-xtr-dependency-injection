from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.kernel import KernelInterface
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter


@dataclass(frozen=True)
class SomeConfig:
    pass


def _loaded(configs: dict[str, object]) -> BuildState:
    bundle = KernelBundle()
    bundle.info.identify(name="shop", environment="dev", debug=True, project_dir=Path("/srv"))
    bundle.provide(configs)
    state = BuildState(env="dev", debug=True, bundles=("kernel",), configs=configs)
    bundle.load(NoConfig(), ServiceConfigurator(state, Origin("kernel", "kernel")))
    return state


def test_the_kernel_bundle_is_named_kernel() -> None:
    assert KernelBundle.metadata().name == "kernel"


def test_it_provides_the_kernel_and_the_resetter() -> None:
    state = _loaded({})

    assert state.store.get((KernelInterface, None)) is not None
    assert state.store.get((ServicesResetter, None)) is not None


def test_it_provides_every_config_but_no_config() -> None:
    state = _loaded({"kernel": NoConfig(), "some": SomeConfig()})

    assert state.store.get((SomeConfig, None)) is not None
    assert state.store.get((NoConfig, None)) is None


def test_it_provides_the_kernel_parameters() -> None:
    state = _loaded({})

    assert state.parameters == [
        (
            "kernel kernel",
            {
                "kernel": {
                    "name": "shop",
                    "environment": "dev",
                    "debug": True,
                    "project_dir": "/srv",
                }
            },
        )
    ]
