"""The core ``kernel`` bundle: always active, always first, never discovered.

It provides what every application may ask for: :class:`KernelInterface`,
the :class:`ServicesResetter`, and — through the kernel wiring in
:func:`_register_kernel_parameters` — the ``kernel.*`` parameters. Every
active bundle's resolved config is also registered under its config type by
the kernel, right after this bundle's ``load_extension`` returns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from typing_extensions import override
from wireup import AsyncContainer
from xtr_service_contracts import ContainerInterface, ResetInterface

from xtr_dependency_injection.bundle import KERNEL_BUNDLE, Bundle, BundleMetadata, NoConfig
from xtr_dependency_injection.bundle.as_bundle import declare_bundle
from xtr_dependency_injection.compiler.check_alias_validity_pass import CheckAliasValidityPass
from xtr_dependency_injection.compiler.pass_stage import PassStage
from xtr_dependency_injection.compiler.register_env_var_processors_pass import (
    ENV_VAR_LOADER_TAG,
    ENV_VAR_PROCESSOR_TAG,
)
from xtr_dependency_injection.compiler.resettable_service_pass import (
    RESET_TAG,
    ResettableServicePass,
)
from xtr_dependency_injection.parameter_bag.container_bag import ContainerBag
from xtr_dependency_injection.parameter_bag.container_bag_interface import ContainerBagInterface
from xtr_dependency_injection.runtime.env_var_loader_interface import EnvVarLoaderInterface
from xtr_dependency_injection.runtime.env_var_processor_interface import EnvVarProcessorInterface
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

# The plan names the one KernelInterface implementation _KernelInfo (§6.5);
# this bundle is the only other module allowed to build it.
from .kernel_interface import KernelInterface, _KernelInfo  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator

__all__ = ["KernelBundle"]


def container_bag(container: ContainerInterface) -> ContainerBagInterface:
    """Expose the compiled container's parameters as an injectable, read-only bag."""
    parameters = cast("WireupContainer", container).get_parameters()
    return ContainerBag(container, parameters)


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
        """Register the kernel's compiler passes and the ``kernel.reset`` autoconfiguration rule.

        :class:`ResettableServicePass` checks every ``kernel.reset`` method
        (``BEFORE_OPTIMIZATION`` -32); :class:`CheckAliasValidityPass` checks
        every alias target implements its alias (``BEFORE_REMOVING``). Every
        non-kernel service implementing ``ResetInterface`` (nominal subclass,
        not structural) gets ``kernel.reset`` with ``method="reset"``; a
        service opts in explicitly with ``add_tag("kernel.reset", method=…)``.
        Every one implementing ``EnvVarProcessorInterface`` or
        ``EnvVarLoaderInterface`` is tagged for ``RegisterEnvVarProcessorsPass``.
        """
        builder.add_compiler_pass(
            ResettableServicePass(), stage=PassStage.BEFORE_OPTIMIZATION, priority=-32
        )
        builder.add_compiler_pass(CheckAliasValidityPass(), stage=PassStage.BEFORE_REMOVING)
        _ = builder.register_for_autoconfiguration(ResetInterface).add_tag(
            RESET_TAG, method="reset"
        )
        _ = builder.register_for_autoconfiguration(EnvVarProcessorInterface).add_tag(
            ENV_VAR_PROCESSOR_TAG
        )
        _ = builder.register_for_autoconfiguration(EnvVarLoaderInterface).add_tag(
            ENV_VAR_LOADER_TAG
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
        _ = services.set(container_bag)
