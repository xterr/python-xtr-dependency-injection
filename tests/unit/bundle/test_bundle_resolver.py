from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.bundle import (
    Bundle,
    BundleMetadata,
    NoConfig,
    as_bundle,
    required_bundle,
)
from xtr_dependency_injection.bundle.as_bundle import declare_bundle
from xtr_dependency_injection.bundle.bundle_resolver import resolve_bundles
from xtr_dependency_injection.exception import (
    BundleDefinitionError,
    CircularBundleDependencyError,
    DuplicateBundleError,
    MissingBundleError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.bundle.bundle import AnyBundle


@dataclass(frozen=True)
class SharedConfig:
    pass


@declare_bundle(BundleMetadata("kernel", NoConfig))
class CoreBundle(Bundle):
    pass


@as_bundle("beta")
class BetaBundle(Bundle):
    pass


@required_bundle(BetaBundle)
@as_bundle("alpha")
class AlphaBundle(Bundle):
    pass


@as_bundle("gamma")
class GammaBundle(Bundle):
    pass


@as_bundle("delta")
class DeltaBundle(Bundle):
    pass


@as_bundle("loop_a")
class LoopA(Bundle):
    pass


@as_bundle("loop_b")
class LoopB(Bundle):
    pass


# Set the loop via required_bundle after both classes exist.
_ = required_bundle(LoopB)(LoopA)
_ = required_bundle(LoopA)(LoopB)


@as_bundle("shared_one", config=SharedConfig)
class SharedOne(Bundle[SharedConfig]):
    pass


@as_bundle("shared_two", config=SharedConfig)
class SharedTwo(Bundle[SharedConfig]):
    pass


@required_bundle("no_such_module_xyz:MissingBundle", ignore_on_invalid=True)
@as_bundle("with_optional_missing")
class WithOptionalMissingBundle(Bundle):
    pass


@required_bundle("no_such_module_xyz:MissingBundle")
@as_bundle("with_required_missing")
class WithRequiredMissingBundle(Bundle):
    pass


class RaisesOnInit(Bundle):
    def __init__(self) -> None:
        raise RuntimeError("do not build me")


# Attach @as_bundle after the class body: as_bundle refuses classes needing arg-less constructor
# checks in the signature, which `RaisesOnInit` still passes — the ctor raises only at build time.
RaisesOnInit = as_bundle("raises_on_init")(RaisesOnInit)  # type: ignore[assignment]


def _resolve(
    listed: Mapping[type[AnyBundle], Mapping[str, bool]],
    *,
    env: str = "dev",
) -> list[str]:
    resolved = resolve_bundles(core=CoreBundle(), listed=listed, env=env)
    return [type(bundle).metadata().name for bundle in resolved.bundles]


def test_a_listed_bundle_active_via_all_is_activated() -> None:
    assert _resolve({BetaBundle: {"all": True}}) == ["kernel", "beta"]


def test_a_listed_bundle_active_only_in_specific_env_is_gated() -> None:
    assert _resolve({BetaBundle: {"dev": True}}, env="dev") == ["kernel", "beta"]
    assert _resolve({BetaBundle: {"dev": True}}, env="prod") == ["kernel"]


def test_a_listed_bundles_env_flag_overrides_the_all_default() -> None:
    assert _resolve({BetaBundle: {"all": True, "prod": False}}, env="prod") == ["kernel"]


def test_a_required_class_is_pulled_in() -> None:
    order = _resolve({AlphaBundle: {"all": True}})

    assert order == ["kernel", "beta", "alpha"]


def test_a_missing_required_string_is_refused() -> None:
    with pytest.raises(MissingBundleError) as caught:
        _ = _resolve({WithRequiredMissingBundle: {"all": True}})

    assert caught.value.name == "no_such_module_xyz:MissingBundle"
    assert caught.value.required_by == "with_required_missing"


def test_a_missing_required_with_ignore_on_invalid_is_skipped() -> None:
    resolved = resolve_bundles(
        core=CoreBundle(),
        listed={WithOptionalMissingBundle: {"all": True}},
        env="dev",
    )

    names = [type(bundle).metadata().name for bundle in resolved.bundles]
    assert names == ["kernel", "with_optional_missing"]
    skipped = [report for report in resolved.reports if report.state == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].qualname == "no_such_module_xyz:MissingBundle"


def test_a_required_bundle_inherits_the_requirers_activity() -> None:
    # Beta is listed but disabled in prod; alpha requires beta and is activated in prod.
    # Because the requirer (alpha) is active, beta becomes active too.
    order = _resolve(
        {AlphaBundle: {"all": True}, BetaBundle: {"prod": False, "all": True}},
        env="prod",
    )

    assert order == ["kernel", "beta", "alpha"]


def test_a_bundle_disabled_in_the_env_is_reported() -> None:
    resolved = resolve_bundles(
        core=CoreBundle(),
        listed={DeltaBundle: {"dev": True}},
        env="prod",
    )

    ((delta,),) = ([r for r in resolved.reports if r.name == "delta"],)
    assert delta.state == "env_disabled"


def test_two_active_bundles_sharing_a_config_type_are_refused() -> None:
    with pytest.raises(BundleDefinitionError, match="already belongs to bundle 'shared_one'"):
        _ = _resolve({SharedOne: {"all": True}, SharedTwo: {"all": True}})


def test_a_dependency_loop_is_refused() -> None:
    with pytest.raises(CircularBundleDependencyError) as caught:
        _ = _resolve({LoopA: {"all": True}, LoopB: {"all": True}})

    assert caught.value.cycle == ("loop_a", "loop_b", "loop_a")


def test_two_listed_bundles_with_the_same_name_are_refused() -> None:
    @as_bundle("clash")
    class ClashA(Bundle):
        pass

    # Give a different class the same name using declare_bundle's escape hatch.
    @declare_bundle(BundleMetadata("clash", NoConfig))
    class ClashB(Bundle):
        pass

    with pytest.raises(DuplicateBundleError):
        _ = _resolve({ClashA: {"all": True}, ClashB: {"all": True}})


def test_only_active_bundle_classes_are_instantiated() -> None:
    # RaisesOnInit raises in its constructor; when disabled it must not be built.
    resolved = resolve_bundles(
        core=CoreBundle(),
        listed={RaisesOnInit: {"prod": True}},
        env="dev",
    )

    assert [type(bundle).metadata().name for bundle in resolved.bundles] == ["kernel"]


def test_a_listed_bundle_raising_when_active_is_refused() -> None:
    with pytest.raises(BundleDefinitionError, match="cannot be built"):
        _ = _resolve({RaisesOnInit: {"all": True}})


def test_a_required_class_that_is_not_a_bundle_is_refused() -> None:
    class NotABundle:
        pass

    _ = required_bundle(NotABundle)(BetaBundle)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    try:
        with pytest.raises(BundleDefinitionError, match="not a Bundle"):
            _ = _resolve({BetaBundle: {"all": True}})
    finally:
        # Restore beta's required tuple so other tests are unaffected.
        setattr(BetaBundle, "__xtr_required_bundles__", ())  # noqa: B010


def test_reports_include_required_names() -> None:
    resolved = resolve_bundles(
        core=CoreBundle(),
        listed={AlphaBundle: {"all": True}},
        env="dev",
    )

    ((alpha_report,),) = ([r for r in resolved.reports if r.name == "alpha"],)
    assert alpha_report.required == ("beta",)
