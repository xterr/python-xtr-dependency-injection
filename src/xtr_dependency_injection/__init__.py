"""A Symfony-style bundle and kernel layer for the xtr libraries, built on wireup.

Each library ships one bundle; installed bundles register themselves; an
application is one ``Kernel("app")`` line plus decorators. What comes out is a
plain wireup ``AsyncContainer``: this package decides *what* goes into it, in
*which order*, *for which environment*, and runs the lifecycle around it.
"""

from __future__ import annotations

from importlib.metadata import version

from .builder import Definition, Origin, ServiceKey
from .builder.container_builder import ContainerBuilder
from .builder.service_configurator import ServiceConfigurator
from .bundle import Bundle, BundleMetadata, NoConfig, as_bundle
from .config import configure, env, parameters
from .config.config_prepender import ConfigPrepender
from .decorator import (
    Inner,
    as_decorator,
    compiler_pass,
    exclude,
    on_boot,
    on_shutdown,
    when,
    when_not,
)
from .diagnostics import KernelReport
from .discovery import DiscoveredBundle, discover_bundles
from .kernel import BootedKernel, CompiledKernel, Kernel, KernelInterface
from .runtime import ServiceLocator, ServicesResetter, bind_callable
from .scan import DEFAULT_EXCLUDES
from .standalone import injectables

__all__ = [
    "DEFAULT_EXCLUDES",
    "BootedKernel",
    "Bundle",
    "BundleMetadata",
    "CompiledKernel",
    "ConfigPrepender",
    "ContainerBuilder",
    "Definition",
    "DiscoveredBundle",
    "Inner",
    "Kernel",
    "KernelInterface",
    "KernelReport",
    "NoConfig",
    "Origin",
    "ServiceConfigurator",
    "ServiceKey",
    "ServiceLocator",
    "ServicesResetter",
    "as_bundle",
    "as_decorator",
    "bind_callable",
    "compiler_pass",
    "configure",
    "discover_bundles",
    "env",
    "exclude",
    "injectables",
    "on_boot",
    "on_shutdown",
    "parameters",
    "when",
    "when_not",
]

__version__ = version("xtr-dependency-injection")
