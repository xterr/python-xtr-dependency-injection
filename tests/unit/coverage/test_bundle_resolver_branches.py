"""Cover ``bundle_resolver`` error paths not otherwise exercised."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection import Bundle, NoConfig, as_bundle, required_bundle
from xtr_dependency_injection.bundle.bundle_resolver import resolve_bundles

if TYPE_CHECKING:
    from xtr_dependency_injection.bundle.bundle import AnyBundle
from xtr_dependency_injection.exception import (
    BundleDefinitionError,
    DuplicateBundleError,
    MissingBundleError,
)
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle


class _NotABundle:
    pass


def test_a_listed_class_without_as_bundle_raises() -> None:
    with pytest.raises(BundleDefinitionError, match="not decorated with @as_bundle"):
        _ = resolve_bundles(
            core=KernelBundle(),
            listed={cast("type[AnyBundle]", _NotABundle): {"all": True}},
            env="test",
        )


def test_a_missing_required_bundle_without_ignore_raises_missing_bundle_error() -> None:
    @required_bundle("no_such_module_xyz_abc:Missing")
    @as_bundle("needs_missing", config=NoConfig)
    class NeedsMissing(Bundle[NoConfig]):
        pass

    with pytest.raises(MissingBundleError):
        _ = resolve_bundles(core=KernelBundle(), listed={NeedsMissing: {"all": True}}, env="test")


def test_a_required_target_that_is_not_a_bundle_class_raises() -> None:
    module = ModuleType("_xtr_probe_not_a_bundle")
    setattr(module, "NotBundle", _NotABundle)  # noqa: B010
    sys.modules["_xtr_probe_not_a_bundle"] = module

    @required_bundle("_xtr_probe_not_a_bundle:NotBundle")
    @as_bundle("needs_stranger", config=NoConfig)
    class NeedsStranger(Bundle[NoConfig]):
        pass

    try:
        with pytest.raises(BundleDefinitionError, match="is not a Bundle subclass"):
            _ = resolve_bundles(
                core=KernelBundle(),
                listed={NeedsStranger: {"all": True}},
                env="test",
            )
    finally:
        del sys.modules["_xtr_probe_not_a_bundle"]


def test_a_required_ignored_target_records_skipped() -> None:
    @required_bundle("no_such_module_xyz_ignored:X", ignore_on_invalid=True)
    @as_bundle("host_ignored", config=NoConfig)
    class HostIgnored(Bundle[NoConfig]):
        pass

    resolved = resolve_bundles(core=KernelBundle(), listed={HostIgnored: {"all": True}}, env="test")
    states = {report.state for report in resolved.reports}
    assert "skipped" in states


def test_two_required_bundles_with_the_same_name_raise_duplicate() -> None:
    @as_bundle("clash", config=NoConfig)
    class One(Bundle[NoConfig]):
        pass

    @as_bundle("clash", config=NoConfig)
    class Two(Bundle[NoConfig]):
        pass

    @required_bundle(One)
    @required_bundle(Two)
    @as_bundle("host_clash", config=NoConfig)
    class Host(Bundle[NoConfig]):
        pass

    with pytest.raises(DuplicateBundleError):
        _ = resolve_bundles(core=KernelBundle(), listed={Host: {"all": True}}, env="test")
