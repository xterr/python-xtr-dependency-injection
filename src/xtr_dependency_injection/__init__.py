"""A bundle and kernel layer for the xtr libraries, built on wireup.

Each library ships one bundle; installed bundles register themselves; an
application is one ``Kernel("app")`` line plus decorators. What comes out is a
plain wireup ``AsyncContainer``: this package decides *what* goes into it, in
*which order*, *for which environment*, and runs the lifecycle around it.
"""

from __future__ import annotations

from importlib.metadata import version

from .builder import Decorates, Definition, Origin, ServiceKey
from .builder.bundle_active import bundle_active
from .builder.container_builder import ContainerBuilder
from .builder.named_factory import named_factory
from .builder.service_configurator import ServiceConfigurator
from .bundle import Bundle, BundleMetadata, NoConfig, RequiredBundle, as_bundle, required_bundle
from .compiler.compiler_pass_interface import CompilerPassInterface
from .compiler.pass_stage import PassStage
from .config import AliasOf, configure, env, one_or_many, parameters
from .decorator import (
    Autowire,
    AutowireDecorated,
    Injected,
    OnInvalid,
    Target,
    as_alias,
    as_decorator,
    as_service,
    as_tagged_item,
    autoconfigure,
    autoconfigure_tag,
    compiler_pass,
    exclude,
    is_container_supplied,
    on_boot,
    on_shutdown,
    remove_if_missing,
    when,
    when_not,
)
from .diagnostics import KernelReport
from .exception._naming import qualified_name
from .kernel import BootedKernel, CompiledKernel, Kernel, KernelInterface
from .parameter_bag import ContainerBagInterface, ParameterBagInterface
from .runtime import (
    EnvVarLoaderInterface,
    EnvVarProcessor,
    EnvVarProcessorInterface,
    Reference,
    ServiceLocator,
    ServicesResetter,
    bind_callable,
    optional_service,
)
from .scan import DEFAULT_EXCLUDES

__all__ = [
    "DEFAULT_EXCLUDES",
    "AliasOf",
    "Autowire",
    "AutowireDecorated",
    "BootedKernel",
    "Bundle",
    "BundleMetadata",
    "CompiledKernel",
    "CompilerPassInterface",
    "ContainerBagInterface",
    "ContainerBuilder",
    "Decorates",
    "Definition",
    "EnvVarLoaderInterface",
    "EnvVarProcessor",
    "EnvVarProcessorInterface",
    "Injected",
    "Kernel",
    "KernelInterface",
    "KernelReport",
    "NoConfig",
    "OnInvalid",
    "Origin",
    "ParameterBagInterface",
    "PassStage",
    "Reference",
    "RequiredBundle",
    "ServiceConfigurator",
    "ServiceKey",
    "ServiceLocator",
    "ServicesResetter",
    "Target",
    "as_alias",
    "as_bundle",
    "as_decorator",
    "as_service",
    "as_tagged_item",
    "autoconfigure",
    "autoconfigure_tag",
    "bind_callable",
    "bundle_active",
    "compiler_pass",
    "configure",
    "env",
    "exclude",
    "is_container_supplied",
    "named_factory",
    "on_boot",
    "on_shutdown",
    "one_or_many",
    "optional_service",
    "parameters",
    "qualified_name",
    "remove_if_missing",
    "required_bundle",
    "when",
    "when_not",
]

__version__ = version("xtr-dependency-injection")
