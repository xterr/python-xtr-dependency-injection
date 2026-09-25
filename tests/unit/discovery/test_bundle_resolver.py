from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.bundle import Bundle, BundleMetadata, NoConfig, as_bundle
from xtr_dependency_injection.bundle.as_bundle import declare_bundle
from xtr_dependency_injection.discovery import DiscoveredBundle
from xtr_dependency_injection.discovery.bundle_resolver import resolve_bundles
from xtr_dependency_injection.exception import (
    BundleDefinitionError,
    CircularBundleDependencyError,
    DuplicateBundleError,
    MissingBundleError,
)

if TYPE_CHECKING:
    from xtr_dependency_injection.bundle.bundle import AnyBundle


@dataclass(frozen=True)
class SharedConfig:
    pass


@declare_bundle(BundleMetadata("kernel", NoConfig))
class CoreBundle(Bundle):
    pass


@as_bundle("alpha", requires=("beta",), optional=("gamma",))
class AlphaBundle(Bundle):
    pass


@as_bundle("beta")
class BetaBundle(Bundle):
    pass


@as_bundle("gamma", envs=("dev",))
class GammaBundle(Bundle):
    pass


@as_bundle("delta")
class DeltaBundle(Bundle):
    pass


@as_bundle("loop_a", requires=("loop_b",))
class LoopA(Bundle):
    pass


@as_bundle("loop_b", optional=("loop_a",))
class LoopB(Bundle):
    pass


@as_bundle("shared_one", config=SharedConfig)
class SharedOne(Bundle[SharedConfig]):
    pass


@as_bundle("shared_two", config=SharedConfig)
class SharedTwo(Bundle[SharedConfig]):
    pass


def _found(*bundles: type[AnyBundle]) -> tuple[DiscoveredBundle, ...]:
    return tuple(
        DiscoveredBundle(b.metadata().name, f"x:{b.__name__}", "dist", b, None) for b in bundles
    )


def _resolve(
    discovered: tuple[DiscoveredBundle, ...],
    *,
    explicit: list[AnyBundle] | None = None,
    exclude: tuple[str, ...] = (),
    bundle_envs: dict[str, tuple[str, ...]] | None = None,
    env: str = "dev",
) -> list[str]:
    resolved = resolve_bundles(
        core=CoreBundle(),
        discovered=discovered,
        explicit=explicit,
        exclude=exclude,
        bundle_envs=bundle_envs,
        env=env,
    )
    return [type(bundle).metadata().name for bundle in resolved.bundles]


def test_every_discovered_bundle_is_active_in_dependency_order() -> None:
    order = _resolve(_found(DeltaBundle, AlphaBundle, BetaBundle, GammaBundle))

    assert order == ["kernel", "beta", "delta", "gamma", "alpha"]


def test_an_env_disabled_optional_peer_does_not_order_anything() -> None:
    assert _resolve(_found(AlphaBundle, BetaBundle, GammaBundle), env="prod") == [
        "kernel",
        "beta",
        "alpha",
    ]


def test_bundle_envs_override_a_bundles_own() -> None:
    order = _resolve(_found(GammaBundle), bundle_envs={"gamma": ("prod",)}, env="prod")

    assert order == ["kernel", "gamma"]


def test_an_explicit_list_pulls_in_what_it_requires() -> None:
    resolved = resolve_bundles(
        core=CoreBundle(),
        discovered=_found(BetaBundle, DeltaBundle),
        explicit=[AlphaBundle()],
        exclude=(),
        bundle_envs=None,
        env="dev",
    )

    assert [(report.name, report.source) for report in resolved.reports] == [
        ("kernel", "explicit"),
        ("beta", "required"),
        ("alpha", "explicit"),
    ]


def test_the_explicit_instance_is_the_one_used() -> None:
    alpha = AlphaBundle()
    resolved = resolve_bundles(
        core=CoreBundle(),
        discovered=_found(BetaBundle),
        explicit=[alpha],
        exclude=(),
        bundle_envs=None,
        env="dev",
    )

    assert resolved.bundles[-1] is alpha


def test_a_missing_requirement_is_refused() -> None:
    with pytest.raises(MissingBundleError) as caught:
        _ = _resolve(_found(AlphaBundle))

    assert (caught.value.name, caught.value.required_by, caught.value.reason) == (
        "beta",
        "alpha",
        None,
    )


def test_a_skipped_requirement_carries_the_skip_reason() -> None:
    skipped = DiscoveredBundle("beta", "x:Beta", "dist", None, "cannot import x")

    with pytest.raises(MissingBundleError) as caught:
        _ = _resolve((*_found(AlphaBundle), skipped))

    assert caught.value.reason == "cannot import x"


def test_a_skipped_bundle_nothing_needs_is_only_reported() -> None:
    skipped = DiscoveredBundle("broken", "x:Broken", "dist", None, "cannot import x")
    resolved = resolve_bundles(
        core=CoreBundle(),
        discovered=(skipped,),
        explicit=None,
        exclude=(),
        bundle_envs=None,
        env="dev",
    )

    assert resolved.reports[-1].state == "skipped"
    assert resolved.reports[-1].reason == "cannot import x"


def test_an_excluded_bundle_is_reported_as_excluded() -> None:
    resolved = resolve_bundles(
        core=CoreBundle(),
        discovered=_found(DeltaBundle),
        explicit=None,
        exclude=("delta",),
        bundle_envs=None,
        env="dev",
    )

    assert [(report.name, report.state) for report in resolved.reports] == [
        ("kernel", "active"),
        ("delta", "excluded"),
    ]


def test_excluding_a_required_bundle_is_refused() -> None:
    with pytest.raises(MissingBundleError, match="listed in exclude_bundles"):
        _ = _resolve(_found(AlphaBundle, BetaBundle), exclude=("beta",))


def test_a_required_bundle_disabled_in_the_env_is_refused() -> None:
    with pytest.raises(MissingBundleError, match="active only in: dev"):
        _ = _resolve(_found(AlphaBundle, BetaBundle), bundle_envs={"beta": ("dev",)}, env="prod")


def test_the_kernel_bundle_cannot_be_excluded() -> None:
    with pytest.raises(BundleDefinitionError, match="cannot be excluded"):
        _ = _resolve((), exclude=("kernel",))


def test_a_dependency_loop_is_refused() -> None:
    with pytest.raises(CircularBundleDependencyError) as caught:
        _ = _resolve(_found(LoopA, LoopB))

    assert caught.value.cycle == ("loop_a", "loop_b", "loop_a")


def test_two_listed_bundles_with_one_name_are_refused() -> None:
    with pytest.raises(DuplicateBundleError):
        _ = _resolve((), explicit=[DeltaBundle(), DeltaBundle()])


def test_two_active_bundles_sharing_a_config_type_are_refused() -> None:
    with pytest.raises(BundleDefinitionError, match="already belongs to bundle 'shared_one'"):
        _ = _resolve(_found(SharedOne, SharedTwo))


def test_a_bundle_that_cannot_be_built_is_refused() -> None:
    @as_bundle("fragile")
    class Fragile(Bundle):
        def __init__(self) -> None:
            raise RuntimeError("no")

    with pytest.raises(BundleDefinitionError, match="cannot be built"):
        _ = _resolve(_found(Fragile))
