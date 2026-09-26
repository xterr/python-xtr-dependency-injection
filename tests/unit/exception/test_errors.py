from __future__ import annotations

import pytest

from xtr_dependency_injection import exception
from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.exception import (
    BuilderFrozenError,
    BuilderPhaseError,
    BundleDefinitionError,
    CircularBundleDependencyError,
    ConfigProviderError,
    ConflictingConfigProvidersError,
    ContainerCompilationError,
    DecoratorSignatureError,
    DependencyInjectionError,
    DuplicateBundleError,
    DuplicateServiceError,
    InvalidEnvironmentError,
    InvalidEnvironmentVariableError,
    KernelAlreadyBootedError,
    MissingBundleError,
    MissingEnvironmentVariableError,
    ParameterConflictError,
    ParameterNotFoundError,
    ResourceImportError,
    ServiceNotFoundError,
    ServiceResolutionError,
    UnknownConfigTypeError,
    UnknownLocatorKeyError,
    UnknownServiceError,
)


class Sample:
    pass


def test_every_exported_error_derives_from_the_root() -> None:
    for name in exception.__all__:
        assert issubclass(getattr(exception, name), DependencyInjectionError)


def test_bundle_definition_error_carries_the_bundle_and_reason() -> None:
    error = BundleDefinitionError("logging", "the name is reserved")

    assert (error.bundle, error.reason) == ("logging", "the name is reserved")
    assert str(error) == "invalid bundle logging: the name is reserved"


def test_duplicate_bundle_error_carries_both_claimants() -> None:
    error = DuplicateBundleError("alpha", "a:Alpha", "b:Alpha")

    assert (error.name, error.first, error.second) == ("alpha", "a:Alpha", "b:Alpha")
    assert str(error) == "bundle name 'alpha' is claimed by both a:Alpha and b:Alpha"


def test_missing_bundle_error_names_who_required_it_and_why() -> None:
    error = MissingBundleError("beta", "alpha", "ImportError: no module")

    assert (error.name, error.required_by, error.reason) == (
        "beta",
        "alpha",
        "ImportError: no module",
    )
    assert (
        str(error) == "bundle 'beta' (required by alpha) is not available: ImportError: no module"
    )


def test_missing_bundle_error_says_explicit_and_not_installed_by_default() -> None:
    error = MissingBundleError("beta", None, None)

    assert str(error) == "bundle 'beta' (listed explicitly) is not available: it is not installed"


def test_circular_bundle_dependency_error_shows_the_loop() -> None:
    error = CircularBundleDependencyError(("a", "b", "a"))

    assert error.cycle == ("a", "b", "a")
    assert str(error) == "circular bundle dependency: a -> b -> a"


def test_invalid_environment_error_lists_the_allowed() -> None:
    error = InvalidEnvironmentError("qa", ("dev", "prod"))

    assert (error.env, error.allowed) == ("qa", ("dev", "prod"))
    assert str(error) == "environment 'qa' is not allowed; allowed: dev, prod"


def test_resource_import_error_names_the_module() -> None:
    error = ResourceImportError("app.broken")

    assert error.module == "app.broken"
    assert str(error) == "cannot import scanned module 'app.broken'"


def test_config_provider_error_carries_the_provider_and_reason() -> None:
    error = ConfigProviderError("app.config:logging", "bad return")

    assert (error.provider, error.reason) == ("app.config:logging", "bad return")
    assert str(error) == "invalid provider app.config:logging: bad return"


def test_unknown_config_type_error_names_the_inactive_bundle() -> None:
    error = UnknownConfigTypeError("app.config:f", Sample, "logging")

    assert (error.provider, error.config_type, error.inactive_bundle) == (
        "app.config:f",
        Sample,
        "logging",
    )
    assert str(error) == (
        f"app.config:f configures {__name__}.Sample, but its bundle 'logging' is not active"
    )


def test_unknown_config_type_error_says_when_no_bundle_declares_it() -> None:
    error = UnknownConfigTypeError("app.config:f", Sample, None)

    assert str(error).endswith("but no bundle declares it")


def test_conflicting_config_providers_error_lists_the_providers() -> None:
    error = ConflictingConfigProvidersError(Sample, ("a:f", "b:g"))

    assert (error.config_type, error.providers) == (Sample, ("a:f", "b:g"))
    assert str(error) == f"{__name__}.Sample has more than one base provider: a:f, b:g"


def test_parameter_conflict_error_shows_the_dotted_path() -> None:
    error = ParameterConflictError(("db", "url"), "bundle logging", "app.p:params")

    assert (error.path, error.first, error.second) == (
        ("db", "url"),
        "bundle logging",
        "app.p:params",
    )
    assert str(error) == "parameter 'db.url' is set by both bundle logging and app.p:params"


def test_missing_environment_variable_error_names_the_variable() -> None:
    error = MissingEnvironmentVariableError("DSN")

    assert error.name == "DSN"
    assert str(error) == "environment variable DSN is not set and has no default"


def test_invalid_environment_variable_error_names_the_conversion() -> None:
    error = InvalidEnvironmentVariableError("PORT", int, "abc")

    assert (error.name, error.cast, error.value) == ("PORT", int, "abc")
    assert str(error) == "environment variable PORT='abc' is not a valid int"


def test_duplicate_service_error_names_the_key_and_both_origins() -> None:
    first = Origin("bundle", "alpha")
    second = Origin("bundle", "beta")
    error = DuplicateServiceError((Sample, "q"), first, second)

    assert (error.key, error.first, error.second) == ((Sample, "q"), first, second)
    assert str(error) == f"{__name__}.Sample['q'] is defined by both bundle alpha and bundle beta"


def test_unknown_service_error_names_the_operation() -> None:
    error = UnknownServiceError((Sample, None), "decorate")

    assert (error.key, error.operation) == ((Sample, None), "decorate")
    assert str(error) == f"cannot decorate {__name__}.Sample: no service is defined for it"


def test_decorator_signature_error_carries_the_decorator_and_reason() -> None:
    reason = "no AutowireDecorated parameter"
    error = DecoratorSignatureError("app:Tracing", reason)

    assert (error.decorator, error.reason) == ("app:Tracing", reason)
    assert str(error) == f"invalid decorator app:Tracing: {reason}"


def test_builder_phase_error_names_the_operation_and_phase() -> None:
    error = BuilderPhaseError("scan", "process")

    assert (error.operation, error.phase) == ("scan", "process")
    assert str(error) == "scan() cannot be called during the process phase"


def test_builder_frozen_error_names_the_operation() -> None:
    error = BuilderFrozenError("factory")

    assert error.operation == "factory"
    assert str(error) == "factory() cannot be called: the container is already compiled"


def test_kernel_already_booted_error_says_to_build_again() -> None:
    assert "build a new one" in str(KernelAlreadyBootedError())


def test_unknown_locator_key_error_lists_the_known_keys() -> None:
    error = UnknownLocatorKeyError("x", ("a", "b"))

    assert (error.key, error.known) == ("x", ("a", "b"))
    assert str(error) == "unknown locator key 'x'; known: 'a', 'b'"


def test_unknown_locator_key_error_shows_none_when_empty() -> None:
    assert str(UnknownLocatorKeyError("x", ())).endswith("known: <none>")


def test_a_raised_error_is_caught_as_the_root() -> None:
    with pytest.raises(DependencyInjectionError):
        raise BuilderFrozenError("scan")


def test_service_not_found_error_is_a_lookup_error() -> None:
    error = ServiceNotFoundError((Sample, "q"))

    assert error.key == (Sample, "q")
    assert isinstance(error, LookupError)
    assert str(error) == f"{__name__}.Sample['q'] is not registered in the container"


def test_parameter_not_found_error_is_a_lookup_error() -> None:
    error = ParameterNotFoundError("kernel.nope")

    assert error.name == "kernel.nope"
    assert isinstance(error, LookupError)
    assert str(error) == "parameter 'kernel.nope' is not defined"


def test_container_compilation_error_carries_the_engine_message() -> None:
    error = ContainerCompilationError("cannot build service X")

    assert error.reason == "cannot build service X"
    assert str(error) == "cannot build service X"
    assert isinstance(error, DependencyInjectionError)


def test_service_resolution_error_carries_the_key() -> None:
    error = ServiceResolutionError((Sample, "q"))

    assert error.key == (Sample, "q")
    assert str(error) == f"failed to resolve {__name__}.Sample['q'] from the container"
    assert isinstance(error, DependencyInjectionError)
