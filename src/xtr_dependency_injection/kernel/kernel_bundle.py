"""The core ``kernel`` bundle: always active, always first, never discovered.

It provides what every application may ask for: ``KernelInterface``, the
``ServicesResetter``, the ``kernel.*`` parameters, and every active bundle's
resolved config under its config type — so a service can inject
``LoggingConfig``. A library bundle therefore never registers its own config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from xtr_dependency_injection.bundle import Bundle, BundleMetadata, NoConfig
from xtr_dependency_injection.bundle.as_bundle import declare_bundle
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter

# The plan names the one KernelInterface implementation _KernelInfo (§6.5);
# this bundle is the only other module allowed to build it.
from .kernel_interface import KernelInterface, _KernelInfo  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator

__all__ = ["KernelBundle"]


@final
@declare_bundle(BundleMetadata("kernel", NoConfig))
class KernelBundle(Bundle):
    """Provides the kernel's own services to every container."""

    def __init__(self) -> None:
        """Create the kernel's info and resetter; the kernel fills in the info as it builds."""
        self.info: _KernelInfo = _KernelInfo()
        self.resetter: ServicesResetter = ServicesResetter()
        self._configs: Mapping[str, object] = {}

    def provide(self, configs: Mapping[str, object]) -> None:
        """Register ``configs`` — every active bundle's resolved config — when loading."""
        self._configs = configs

    @override
    def load(self, config: NoConfig, services: ServiceConfigurator) -> None:
        del config
        services.instance(self.info, as_type=KernelInterface)
        services.instance(self.resetter, as_type=ServicesResetter)
        services.parameters(
            {
                "kernel": {
                    "name": self.info.name,
                    "environment": self.info.environment,
                    "debug": self.info.debug,
                    "project_dir": str(self.info.project_dir),
                }
            }
        )
        for value in self._configs.values():
            if not isinstance(value, NoConfig):
                services.instance(value, as_type=type(value))
