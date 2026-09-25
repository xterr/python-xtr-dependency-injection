from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest
from typing_extensions import override

from xtr_dependency_injection.bundle import Bundle, BundleMetadata, NoConfig, as_bundle
from xtr_dependency_injection.bundle.as_bundle import declare_bundle
from xtr_dependency_injection.config.config_provider import provider_name
from xtr_dependency_injection.config.config_resolver import resolve_configs
from xtr_dependency_injection.config.configure import configure
from xtr_dependency_injection.decorator.when import when
from xtr_dependency_injection.exception import (
    ConfigProviderError,
    ConflictingConfigProvidersError,
    UnknownConfigTypeError,
)
from xtr_dependency_injection.scan.scanned_object import ScannedObject

if TYPE_CHECKING:
    from collections.abc import Callable

    from xtr_dependency_injection.bundle.bundle import AnyBundle
    from xtr_dependency_injection.config.config_prepender import ConfigPrepender


@dataclass(frozen=True)
class LogConfig:
    channels: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrphanConfig:
    pass


@declare_bundle(BundleMetadata("kernel", NoConfig))
class CoreBundle(Bundle):
    pass


@as_bundle("log", config=LogConfig)
class LogBundle(Bundle[LogConfig]):
    pass


@as_bundle("bus", optional=("log", "absent"))
class BusBundle(Bundle):
    @override
    def prepend(self, configs: ConfigPrepender) -> None:
        if configs.has_bundle("log"):
            configs.transform("log", _add_channel("bus"))
        configs.transform("absent", _add_channel("never"))


@as_bundle("typed")
class TypedPrependBundle(Bundle):
    @override
    def prepend(self, configs: ConfigPrepender) -> None:
        configs.transform(LogConfig, _add_channel("typed"))


@as_bundle("rogue")
class RoguePrependBundle(Bundle):
    @override
    def prepend(self, configs: ConfigPrepender) -> None:
        configs.transform("log", lambda _config: "not a config")


@as_bundle("to_no_config")
class NoConfigTargetBundle(Bundle):
    @override
    def prepend(self, configs: ConfigPrepender) -> None:
        configs.transform("kernel", lambda config: config)


def _add_channel(channel: str) -> Callable[[LogConfig], LogConfig]:
    def add(config: LogConfig) -> LogConfig:
        return replace(config, channels=(*config.channels, channel))

    return add


def _scanned(*functions: Callable[..., object]) -> list[ScannedObject]:
    return [ScannedObject(fn, provider_name(fn), None, order) for order, fn in enumerate(functions)]


def _resolve(
    *functions: Callable[..., object],
    bundles: tuple[AnyBundle, ...] | None = None,
    env: str = "prod",
    given: tuple[object, ...] = (),
) -> tuple[object, tuple[str, ...]]:
    bundles = bundles if bundles is not None else (CoreBundle(), LogBundle())
    resolved = resolve_configs(
        bundles=bundles, providers=_scanned(*functions), inactive={}, env=env, given=given
    )
    (report,) = [report for report in resolved.reports if report.bundle == "log"]
    return resolved.values["log"], report.steps


@configure
def base_a() -> LogConfig:
    return LogConfig(("a",))


@configure
def base_b() -> LogConfig:
    return LogConfig(("b",))


@configure
@when("prod")
def base_prod() -> LogConfig:
    return LogConfig(("prod",))


@configure
@when("prod")
def base_prod_again() -> LogConfig:
    return LogConfig(("prod2",))


@configure
def transform_x(config: LogConfig) -> LogConfig:
    return replace(config, channels=(*config.channels, "x"))


@configure(priority=5)
def transform_first(config: LogConfig) -> LogConfig:
    return replace(config, channels=(*config.channels, "first"))


@configure
@when("prod")
def transform_prod(config: LogConfig) -> LogConfig:
    return replace(config, channels=(*config.channels, "prod-t"))


@configure
def orphan() -> OrphanConfig:
    return OrphanConfig()


def test_with_no_provider_the_config_is_its_default() -> None:
    assert _resolve() == (LogConfig(), ("default",))


def test_a_base_provider_replaces_the_default() -> None:
    value, steps = _resolve(base_a)

    assert value == LogConfig(("a",))
    assert steps == ("default", f"base {__name__}:base_a")


def test_a_conditional_base_beats_an_unconditional_one() -> None:
    value, _ = _resolve(base_a, base_prod)

    assert value == LogConfig(("prod",))


def test_two_unconditional_bases_conflict() -> None:
    with pytest.raises(ConflictingConfigProvidersError) as caught:
        _ = _resolve(base_a, base_b)

    assert caught.value.providers == (f"{__name__}:base_a", f"{__name__}:base_b")


def test_two_conditional_bases_conflict() -> None:
    with pytest.raises(ConflictingConfigProvidersError):
        _ = _resolve(base_prod, base_prod_again)


def test_transforms_run_by_priority_then_scan_order_unconditional_first() -> None:
    value, steps = _resolve(transform_prod, transform_x, transform_first, base_a)

    assert value == LogConfig(("a", "first", "x", "prod-t"))
    assert steps[1:] == (
        f"base {__name__}:base_a",
        f"transform {__name__}:transform_first",
        f"transform {__name__}:transform_x",
        f"transform {__name__}:transform_prod",
    )


def test_prepends_apply_after_the_base_and_before_transforms() -> None:
    value, steps = _resolve(base_a, transform_x, bundles=(CoreBundle(), LogBundle(), BusBundle()))

    assert value == LogConfig(("a", "bus", "x"))
    assert steps == (
        "default",
        f"base {__name__}:base_a",
        "prepend bus",
        f"transform {__name__}:transform_x",
    )


def test_a_prepend_may_target_a_config_type() -> None:
    value, _ = _resolve(bundles=(CoreBundle(), LogBundle(), TypedPrependBundle()))

    assert value == LogConfig(("typed",))


def test_a_prepend_to_an_inactive_bundle_is_reported_as_skipped() -> None:
    resolved = resolve_configs(
        bundles=(CoreBundle(), BusBundle()), providers=[], inactive={}, env="prod"
    )

    ((prepend, reason),) = resolved.skipped
    assert prepend.endswith("(prepend by bundle bus)")
    assert reason == "target bundle is not active"


def test_a_prepend_returning_another_type_is_refused() -> None:
    with pytest.raises(ConfigProviderError, match="prepend by bundle rogue"):
        _ = _resolve(bundles=(CoreBundle(), LogBundle(), RoguePrependBundle()))


def test_a_prepend_to_a_bundle_without_config_is_refused() -> None:
    with pytest.raises(ConfigProviderError, match="takes no config"):
        _ = _resolve(bundles=(CoreBundle(), NoConfigTargetBundle()))


def test_a_provider_for_a_type_no_bundle_owns_is_refused() -> None:
    with pytest.raises(UnknownConfigTypeError) as caught:
        _ = _resolve(orphan)

    assert caught.value.inactive_bundle is None


def test_a_provider_for_an_inactive_bundle_names_it() -> None:
    with pytest.raises(UnknownConfigTypeError) as caught:
        _ = resolve_configs(
            bundles=(CoreBundle(),),
            providers=_scanned(orphan),
            inactive={OrphanConfig: "orphans"},
            env="prod",
        )

    assert caught.value.inactive_bundle == "orphans"


def test_a_given_config_acts_as_the_base() -> None:
    value, steps = _resolve(given=(LogConfig(("given",)),))

    assert value == LogConfig(("given",))
    assert steps == ("default", "injectables(configs=...)")


def test_a_given_config_conflicts_with_an_unconditional_base() -> None:
    with pytest.raises(ConflictingConfigProvidersError):
        _ = _resolve(base_a, given=(LogConfig(),))


def test_a_given_config_of_an_unowned_type_is_refused() -> None:
    with pytest.raises(UnknownConfigTypeError):
        _ = _resolve(given=(OrphanConfig(),))


def test_a_bundle_without_config_resolves_to_no_config() -> None:
    resolved = resolve_configs(bundles=(CoreBundle(),), providers=[], inactive={}, env="prod")

    assert resolved.values == {"kernel": NoConfig()}
    assert resolved.reports[0].steps == ("default",)
