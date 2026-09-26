from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

from tests.support.bundles import EchoBundle, EchoConfig
from xtr_dependency_injection.builder import Origin
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.service_configurator import BuildState, ServiceConfigurator
from xtr_dependency_injection.bundle import Bundle, as_bundle
from xtr_dependency_injection.compiler.merge_extension_configuration_pass import (
    MergeExtensionConfigurationPass,
)
from xtr_dependency_injection.diagnostics.report import ReportBuilder
from xtr_dependency_injection.exception import ConfigProviderError, UnknownConfigTypeError
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult

if TYPE_CHECKING:
    from xtr_dependency_injection.bundle.bundle import AnyBundle


def _merge(
    state: BuildState,
    bundles: list[AnyBundle],
    *,
    early: ScanResult | None = None,
    inactive: dict[type, str] | None = None,
) -> MergeExtensionConfigurationPass:
    merge = MergeExtensionConfigurationPass(
        bundles=bundles,
        early=early if early is not None else ScanResult(),
        scanner=Scanner(env="dev", exclude=DEFAULT_EXCLUDES),
        inactive=inactive or {},
        report=ReportBuilder(),
    )
    merge.process(ContainerBuilder(state, Origin("kernel", "kernel")))
    return merge


def _state(*bundles: str) -> BuildState:
    return BuildState(env="dev", debug=False, bundles=("kernel", *bundles), configs={})


def test_a_config_of_an_inactive_bundle_names_that_bundle() -> None:
    scanner = Scanner(env="dev", exclude=DEFAULT_EXCLUDES)
    early = scanner.scan(["tests.fixtures.app_kernel.configuration"], owner=None)

    with pytest.raises(UnknownConfigTypeError, match=r"its bundle 'echo' is not active"):
        _ = _merge(_state(), [KernelBundle()], early=early, inactive={EchoConfig: "echo"})


def test_each_bundle_loads_with_its_origin() -> None:
    state = _state("echo")

    _ = _merge(state, [KernelBundle(), EchoBundle()])

    origins = {definition.origin for definition in state.store.entries()}
    assert origins == {Origin("kernel", "kernel"), Origin("bundle", "echo")}
    assert state.configs["echo"] == EchoConfig()


def test_what_bundles_asked_to_scan_is_scanned_late_and_marked() -> None:
    state = _state("chorus")
    ServiceConfigurator(state, Origin("bundle", "chorus")).load("tests.fixtures.app_kernel_late")

    merge = _merge(state, [KernelBundle()])

    assert [scanned.owner for scanned in merge.late.marked] == ["chorus"]
    assert any(d.origin.kind == "bundle" for d in state.store.entries())


def test_it_leaves_the_builder_in_the_process_phase() -> None:
    state = _state()

    _ = _merge(state, [KernelBundle()])

    assert state.phase == "process"


@as_bundle("prepends_kernel")
class PrependsKernelBundle(Bundle):
    @override
    def prepend_extension(self, builder: ContainerBuilder) -> None:
        builder.prepend_extension_config("kernel", lambda config: config)


def test_a_prepend_to_a_bundle_without_config_is_refused() -> None:
    with pytest.raises(ConfigProviderError, match="takes no config"):
        _ = _merge(_state("prepends_kernel"), [KernelBundle(), PrependsKernelBundle()])
