"""Every error this package raises.

All of them derive from :class:`DependencyInjectionError`, so one ``except``
catches anything the kernel can go wrong with, and a narrower one handles a
single cause. Each carries the data a caller needs as typed attributes rather
than forcing a message to be parsed.
"""

from .builder_frozen_error import BuilderFrozenError
from .builder_phase_error import BuilderPhaseError
from .bundle_definition_error import BundleDefinitionError
from .circular_bundle_dependency_error import CircularBundleDependencyError
from .config_provider_error import ConfigProviderError
from .conflicting_config_providers_error import ConflictingConfigProvidersError
from .decorator_signature_error import DecoratorSignatureError
from .dependency_injection_error import DependencyInjectionError
from .duplicate_bundle_error import DuplicateBundleError
from .duplicate_service_error import DuplicateServiceError
from .invalid_environment_error import InvalidEnvironmentError
from .invalid_environment_variable_error import InvalidEnvironmentVariableError
from .kernel_already_booted_error import KernelAlreadyBootedError
from .missing_bundle_error import MissingBundleError
from .missing_environment_variable_error import MissingEnvironmentVariableError
from .parameter_conflict_error import ParameterConflictError
from .resource_import_error import ResourceImportError
from .unknown_config_type_error import UnknownConfigTypeError
from .unknown_locator_key_error import UnknownLocatorKeyError
from .unknown_service_error import UnknownServiceError

__all__ = [
    "BuilderFrozenError",
    "BuilderPhaseError",
    "BundleDefinitionError",
    "CircularBundleDependencyError",
    "ConfigProviderError",
    "ConflictingConfigProvidersError",
    "DecoratorSignatureError",
    "DependencyInjectionError",
    "DuplicateBundleError",
    "DuplicateServiceError",
    "InvalidEnvironmentError",
    "InvalidEnvironmentVariableError",
    "KernelAlreadyBootedError",
    "MissingBundleError",
    "MissingEnvironmentVariableError",
    "ParameterConflictError",
    "ResourceImportError",
    "UnknownConfigTypeError",
    "UnknownLocatorKeyError",
    "UnknownServiceError",
]
