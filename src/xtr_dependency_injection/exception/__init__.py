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
from .container_compilation_error import ContainerCompilationError
from .decorator_signature_error import DecoratorSignatureError
from .dependency_injection_error import DependencyInjectionError
from .duplicate_bundle_error import DuplicateBundleError
from .duplicate_service_error import DuplicateServiceError
from .env_placeholder_error import EnvPlaceholderError
from .invalid_definition_error import InvalidDefinitionError
from .invalid_environment_error import InvalidEnvironmentError
from .invalid_environment_variable_error import InvalidEnvironmentVariableError
from .invalid_parameter_type_error import InvalidParameterTypeError
from .kernel_already_booted_error import KernelAlreadyBootedError
from .missing_bundle_error import MissingBundleError
from .missing_environment_variable_error import MissingEnvironmentVariableError
from .parameter_circular_reference_error import ParameterCircularReferenceError
from .parameter_conflict_error import ParameterConflictError
from .parameter_not_found_error import ParameterNotFoundError
from .resource_import_error import ResourceImportError
from .service_circular_reference_error import ServiceCircularReferenceError
from .service_not_found_error import ServiceNotFoundError
from .service_order_error import ServiceOrderError
from .service_resolution_error import ServiceResolutionError
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
    "ContainerCompilationError",
    "DecoratorSignatureError",
    "DependencyInjectionError",
    "DuplicateBundleError",
    "DuplicateServiceError",
    "EnvPlaceholderError",
    "InvalidDefinitionError",
    "InvalidEnvironmentError",
    "InvalidEnvironmentVariableError",
    "InvalidParameterTypeError",
    "KernelAlreadyBootedError",
    "MissingBundleError",
    "MissingEnvironmentVariableError",
    "ParameterCircularReferenceError",
    "ParameterConflictError",
    "ParameterNotFoundError",
    "ResourceImportError",
    "ServiceCircularReferenceError",
    "ServiceNotFoundError",
    "ServiceOrderError",
    "ServiceResolutionError",
    "UnknownConfigTypeError",
    "UnknownLocatorKeyError",
    "UnknownServiceError",
]
