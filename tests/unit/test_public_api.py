from __future__ import annotations

import xtr_dependency_injection

PUBLIC = {
    "Kernel",
    "CompiledKernel",
    "BootedKernel",
    "KernelInterface",
    "Bundle",
    "NoConfig",
    "as_bundle",
    "BundleMetadata",
    "ServiceConfigurator",
    "ContainerBuilder",
    "ConfigPrepender",
    "Definition",
    "ServiceKey",
    "Origin",
    "configure",
    "parameters",
    "env",
    "when",
    "when_not",
    "exclude",
    "compiler_pass",
    "on_boot",
    "on_shutdown",
    "as_decorator",
    "Inner",
    "bind_callable",
    "ServiceLocator",
    "ServicesResetter",
    "injectables",
    "discover_bundles",
    "DiscoveredBundle",
    "DEFAULT_EXCLUDES",
    "KernelReport",
}


def test_the_public_api_is_exactly_what_the_plan_lists() -> None:
    assert set(xtr_dependency_injection.__all__) == PUBLIC


def test_every_public_name_is_importable() -> None:
    for name in PUBLIC:
        assert getattr(xtr_dependency_injection, name) is not None


def test_the_version_comes_from_the_distribution() -> None:
    assert xtr_dependency_injection.__version__ == "0.1.0"
