from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

from tests.fixtures.app_marked_iface import Iface, Impl
from xtr_dependency_injection.bundle import Bundle, as_bundle
from xtr_dependency_injection.kernel import Kernel

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator

pytestmark = pytest.mark.anyio


def _reads_impl(obj: object) -> tuple[str, ...]:
    return ("mw",) if obj is Impl else ()


def _register_under_iface(obj: object, name: str, services: ServiceConfigurator) -> None:
    if isinstance(obj, type):
        _ = services.set(obj)
        services.alias(Iface, obj, alias_qualifier=name)


@as_bundle("probe")
class ProbeBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, services
        builder.register_attribute_for_autoconfiguration(_reads_impl, _register_under_iface)


async def test_autoconfigure_registers_an_app_marked_class_under_another_key() -> None:
    compiled = Kernel(
        "tests.fixtures.app_marked_iface",
        bundles={ProbeBundle: {"all": True}},
        env="dev",
    ).build()

    assert isinstance(await compiled.container.get(Iface, "mw"), Impl)
    assert isinstance(await compiled.container.get(Impl), Impl)
