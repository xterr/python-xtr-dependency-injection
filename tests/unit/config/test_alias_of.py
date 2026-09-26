"""``AliasOf`` forwards one bundle's field into another bundle's config."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated

import pytest

from xtr_dependency_injection.bundle import Bundle, BundleMetadata, NoConfig, as_bundle
from xtr_dependency_injection.bundle.as_bundle import declare_bundle
from xtr_dependency_injection.config.alias_of import AliasOf, alias_of_fields
from xtr_dependency_injection.config.config_resolver import ResolvedConfigs, resolve_configs
from xtr_dependency_injection.config.configure import configure
from xtr_dependency_injection.exception import (
    CircularBundleDependencyError,
    ConfigProviderError,
    ConflictingConfigProvidersError,
)
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.scan.scanned_object import ScannedObject

if TYPE_CHECKING:
    from collections.abc import Callable

    from xtr_dependency_injection.bundle.bundle import AnyBundle


@dataclass(frozen=True)
class MailConfig:
    host: str = "localhost"


@dataclass(frozen=True)
class AlphaConfig:
    greeting: str = "hi"
    mail: Annotated[MailConfig | None, AliasOf("mail")] = None


@dataclass(frozen=True)
class LoopAConfig:
    other: Annotated[object | None, AliasOf("loop_b")] = None


@dataclass(frozen=True)
class LoopBConfig:
    other: Annotated[object | None, AliasOf("loop_a")] = None


@dataclass(frozen=True)
class SelfConfig:
    same: Annotated[object | None, AliasOf("selfy")] = None


@dataclass(frozen=True)
class BadAlpha:
    mail: Annotated[object | None, AliasOf("mail")] = field(default=None)


@declare_bundle(BundleMetadata("kernel", NoConfig))
class CoreBundle(Bundle):
    pass


@as_bundle("mail", config=MailConfig)
class MailBundle(Bundle[MailConfig]):
    pass


@as_bundle("alpha", config=AlphaConfig)
class AlphaBundle(Bundle[AlphaConfig]):
    pass


@as_bundle("loop_a", config=LoopAConfig)
class LoopABundle(Bundle[LoopAConfig]):
    pass


@as_bundle("loop_b", config=LoopBConfig)
class LoopBBundle(Bundle[LoopBConfig]):
    pass


@as_bundle("selfy", config=SelfConfig)
class SelfBundle(Bundle[SelfConfig]):
    pass


def _scanned(*functions: Callable[..., object]) -> list[ScannedObject]:
    return [
        ScannedObject(fn, qualified_name(fn), None, order) for order, fn in enumerate(functions)
    ]


def _resolve(
    *functions: Callable[..., object],
    bundles: tuple[AnyBundle, ...],
) -> ResolvedConfigs:
    return resolve_configs(
        bundles=bundles,
        providers=_scanned(*functions),
        inactive={},
    )


def test_alias_of_fields_finds_the_forwarding_declaration() -> None:
    assert alias_of_fields(AlphaConfig) == [("mail", "mail")]
    assert alias_of_fields(MailConfig) == []


def test_a_non_none_alias_forwards_to_the_target() -> None:
    @configure
    def alpha() -> AlphaConfig:
        return AlphaConfig(greeting="hi", mail=MailConfig(host="smtp.example"))

    resolved = _resolve(alpha, bundles=(CoreBundle(), AlphaBundle(), MailBundle()))

    assert resolved.values["mail"] == MailConfig(host="smtp.example")


def test_the_alias_step_is_reported_by_name() -> None:
    @configure
    def alpha() -> AlphaConfig:
        return AlphaConfig(mail=MailConfig(host="smtp.example"))

    resolved = _resolve(alpha, bundles=(CoreBundle(), AlphaBundle(), MailBundle()))

    mail_report = next(report for report in resolved.reports if report.bundle == "mail")
    assert "alias_of alpha.mail" in mail_report.steps


def test_a_none_alias_leaves_the_target_at_its_default() -> None:
    resolved = _resolve(bundles=(CoreBundle(), AlphaBundle(), MailBundle()))

    assert resolved.values["mail"] == MailConfig()


def test_an_alias_conflicts_with_the_targets_app_base_provider() -> None:
    @configure
    def alpha() -> AlphaConfig:
        return AlphaConfig(mail=MailConfig(host="smtp.example"))

    @configure
    def mail() -> MailConfig:
        return MailConfig(host="from-base")

    with pytest.raises(ConflictingConfigProvidersError) as caught:
        _ = _resolve(alpha, mail, bundles=(CoreBundle(), AlphaBundle(), MailBundle()))

    assert caught.value.config_type is MailConfig


@declare_bundle(BundleMetadata("alpha_bad", BadAlpha))
class AlphaBadBundle(Bundle[BadAlpha]):
    pass


@configure
def alpha_bad() -> BadAlpha:
    return BadAlpha(mail=object())


def test_a_wrong_type_forwarded_by_the_alias_is_reported() -> None:
    with pytest.raises(ConfigProviderError) as caught:
        _ = _resolve(alpha_bad, bundles=(CoreBundle(), AlphaBadBundle(), MailBundle()))

    assert "alias_of alpha_bad.mail" in str(caught.value)


def test_an_inactive_target_is_reported_as_skipped_not_an_error() -> None:
    @configure
    def alpha() -> AlphaConfig:
        return AlphaConfig(mail=MailConfig(host="smtp.example"))

    resolved = _resolve(alpha, bundles=(CoreBundle(), AlphaBundle()))

    assert ("alias_of alpha.mail", "target bundle is not active") in resolved.skipped


def test_an_owner_after_its_target_in_bundle_order_still_forwards() -> None:
    @configure
    def alpha() -> AlphaConfig:
        return AlphaConfig(mail=MailConfig(host="smtp.example"))

    resolved = _resolve(alpha, bundles=(CoreBundle(), MailBundle(), AlphaBundle()))

    assert resolved.values["mail"] == MailConfig(host="smtp.example")
    assert [report.bundle for report in resolved.reports] == ["kernel", "mail", "alpha"]


@dataclass(frozen=True)
class BetaConfig:
    mail: Annotated[MailConfig | None, AliasOf("mail")] = None


@as_bundle("beta", config=BetaConfig)
class BetaBundle(Bundle[BetaConfig]):
    pass


def test_two_bundles_forwarding_to_one_target_conflict() -> None:
    @configure
    def alpha() -> AlphaConfig:
        return AlphaConfig(mail=MailConfig(host="a"))

    @configure
    def beta() -> BetaConfig:
        return BetaConfig(mail=MailConfig(host="b"))

    with pytest.raises(ConflictingConfigProvidersError) as caught:
        _ = _resolve(alpha, beta, bundles=(CoreBundle(), AlphaBundle(), BetaBundle(), MailBundle()))

    assert caught.value.config_type is MailConfig


def test_an_alias_loop_between_two_bundles_is_a_cycle() -> None:
    with pytest.raises(CircularBundleDependencyError) as caught:
        _ = _resolve(bundles=(CoreBundle(), LoopABundle(), LoopBBundle()))

    assert caught.value.cycle == ("loop_a", "loop_b", "loop_a")


def test_a_bundle_aliasing_to_itself_is_a_cycle() -> None:
    with pytest.raises(CircularBundleDependencyError) as caught:
        _ = _resolve(bundles=(CoreBundle(), SelfBundle()))

    assert caught.value.cycle == ("selfy", "selfy")
