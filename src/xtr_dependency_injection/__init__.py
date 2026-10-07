"""A bundle and kernel layer for the xtr libraries, built on wireup.

Each library ships one bundle; an application lists the bundles it wants in
its ``bundles.py`` — installing a package activates nothing — and the peers a
bundle requires arrive through ``@required_bundle``. What comes out is a
plain wireup ``AsyncContainer``: this package decides *what* goes into it, in
*which order*, *for which environment*, and runs the lifecycle around it.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .builder import Decorates, Definition, Origin, ServiceKey
from .builder.bundle_active import bundle_active
from .builder.container_builder import ContainerBuilder
from .builder.named_factory import named_factory
from .builder.service_configurator import ServiceConfigurator
from .bundle import Bundle, BundleMetadata, NoConfig, RequiredBundle, as_bundle, required_bundle
from .compiler.before_after_sorter import sort_with_priorities
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
from .exception import FastapiIntegrationError
from .exception.qualified_name import qualified_name
from .kernel import BootedKernel, CompiledKernel, Kernel, KernelInterface
from .kernel.kernel import BUNDLE_PASS_PRIORITY
from .parameter_bag import ContainerBagInterface, ParameterBagInterface
from .runtime import (
    EnvVarLoaderInterface,
    EnvVarProcessor,
    EnvVarProcessorInterface,
    Reference,
    ScopeFactoryInterface,
    ServiceLocator,
    ServicesResetter,
    bind_callable,
    current_unit_of_work,
    optional_service,
    unit_of_work,
)
from .scan import DEFAULT_EXCLUDES

__all__ = [
    "BUNDLE_PASS_PRIORITY",
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
    "FastapiIntegrationError",
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
    "ScopeFactoryInterface",
    "ServiceConfigurator",
    "ServiceKey",
    "ServiceLocator",
    "ServicesResetter",
    "Target",
    "__version__",
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
    "current_unit_of_work",
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
    "sort_with_priorities",
    "unit_of_work",
    "when",
    "when_not",
]

try:
    __version__ = version("xtr-dependency-injection")
except PackageNotFoundError:  # pragma: no cover
    # Running from a source tree with no installed metadata to read; having no
    # version is better than refusing to import.
    __version__ = "0+unknown"
