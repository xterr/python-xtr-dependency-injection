"""The core ``kernel`` bundle: always active, always first, never discovered.

It provides what every application may ask for: :class:`KernelInterface`,
the :class:`ServicesResetter`, and — through the kernel wiring in
:func:`_register_kernel_parameters` — the ``kernel.*`` parameters. Every
active bundle's resolved config is also registered under its config type by
the kernel, right after this bundle's ``load_extension`` returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override
from wireup import AsyncContainer
from xtr_service_contracts import ContainerInterface, ResetInterface

from xtr_dependency_injection.bundle import KERNEL_BUNDLE, Bundle, BundleMetadata, NoConfig
from xtr_dependency_injection.bundle.as_bundle import declare_bundle
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

# The plan names the one KernelInterface implementation _KernelInfo (§6.5);
# this bundle is the only other module allowed to build it.
from .kernel_interface import KernelInterface, _KernelInfo  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator

__all__ = ["KernelBundle"]


def container_interface(container: AsyncContainer) -> ContainerInterface:
    """Wrap the engine container behind :class:`ContainerInterface`.

    Registered by :class:`KernelBundle`; wireup evaluates the annotation and
    keys the service under :class:`ContainerInterface`.
    """
    return WireupContainer(container)


@final
@declare_bundle(BundleMetadata(KERNEL_BUNDLE, NoConfig))
class KernelBundle(Bundle):
    """Provides the kernel's own services to every container."""

    def __init__(self) -> None:
        """Create the kernel's info and resetter; the kernel fills in the info as it builds."""
        self.info: _KernelInfo = _KernelInfo()
        self.resetter: ServicesResetter = ServicesResetter()

    @override
    def build(self, builder: ContainerBuilder) -> None:
        """Register the Symfony 8.2 ``kernel.reset`` autoconfiguration.

        Every non-kernel service implementing ``ResetInterface`` (nominal
        subclass, not structural) gets ``kernel.reset`` with ``method="reset"``;
        a service opts in explicitly with ``add_tag("kernel.reset", method=…)``.
        Mirrors ``ServicesBundle::loadExtension`` at
        ``.tmp/symfony/src/Symfony/Component/DependencyInjection/Kernel/ServicesBundle.php:89``.
        """
        _ = builder.register_for_autoconfiguration(ResetInterface).add_tag(
            "kernel.reset", method="reset"
        )

    @override
    def load_extension(
        self, config: NoConfig, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.instance(self.info)
        services.alias(KernelInterface, _KernelInfo)
        _ = services.instance(self.resetter)
        _ = services.set(container_interface)
