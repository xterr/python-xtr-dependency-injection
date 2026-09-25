"""Resolving each bundle's config, one deterministic step at a time.

For every active bundle, in order:

1. its config type's default, ``C()``;
2. the application's base provider, if any — one conditional on the
   environment beats an unconditional one;
3. other bundles' prepends, in bundle order;
4. the application's transforms — unconditional, then conditional; within
   each, by priority, highest first, then in scan order.

Every step is recorded, so ``debug:config`` shows where a value came from.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.diagnostics import ConfigReport
from xtr_dependency_injection.exception import (
    ConfigProviderError,
    ConflictingConfigProvidersError,
    UnknownConfigTypeError,
)

from .config_prepender import ConfigPrepender, Prepend
from .config_provider import ConfigProvider, config_provider_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from xtr_dependency_injection.bundle.bundle import AnyBundle
    from xtr_dependency_injection.scan.scanned_object import ScannedObject

__all__ = ["ResolvedConfigs", "resolve_configs"]

_STANDALONE: Final = "injectables(configs=...)"


@dataclass(frozen=True, slots=True)
class ResolvedConfigs:
    """Every active bundle's resolved config, and how each was reached.

    Attributes:
        values: Resolved config by bundle name, ``NoConfig`` included.
        reports: One per active bundle, in bundle order.
        skipped: ``(prepend, reason)`` for each prepend whose target is not
            active.
    """

    values: Mapping[str, object]
    reports: tuple[ConfigReport, ...]
    skipped: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _Step:
    label: str
    apply: Callable[[object], object]


def resolve_configs(
    *,
    bundles: Sequence[AnyBundle],
    providers: Sequence[ScannedObject],
    inactive: Mapping[type, str],
    env: str,
    given: Sequence[object] = (),
) -> ResolvedConfigs:
    """Return the config of every bundle in ``bundles``, resolved in order.

    Args:
        bundles: The active bundles, in dependency order.
        providers: The ``@configure`` functions the early scan found.
        inactive: Config types of bundles that are not active, by type, for
            a clearer error.
        env: The environment being built.
        given: Config values acting as unconditional base providers — how
            standalone ``injectables()`` receives its configs.

    Raises:
        UnknownConfigTypeError: If a provider or given config targets a type
            no active bundle owns.
        ConflictingConfigProvidersError: If one group has two base
            providers.
        ConfigProviderError: If a provider or prepend returns the wrong type.
    """
    owned = {type(bundle).metadata().config: type(bundle).metadata().name for bundle in bundles}
    parsed = [
        _owned(config_provider_of(cast("Callable[..., object]", scanned.obj)), owned, inactive)
        for scanned in providers
    ]
    for value in given:
        _ = _owner(type(value), _STANDALONE, owned, inactive)
    prepends = _prepends(bundles, env)
    values: dict[str, object] = {}
    reports: list[ConfigReport] = []
    for bundle in bundles:
        metadata = type(bundle).metadata()
        config_type = metadata.config
        steps = (
            _steps(
                metadata.name,
                config_type,
                [provider for provider in parsed if provider.config_type is config_type],
                [value for value in given if type(value) is config_type],
                prepends,
            )
            if config_type is not NoConfig
            else []
        )
        value: object = config_type()
        for step in steps:
            value = step.apply(value)
        values[metadata.name] = value
        reports.append(ConfigReport(metadata.name, value, ("default", *(s.label for s in steps))))
    skipped = tuple(
        (
            f"{prepend.description} (prepend by bundle {prepend.source})",
            "target bundle is not active",
        )
        for prepend in prepends
        if prepend.target is None
    )
    return ResolvedConfigs(values, tuple(reports), skipped)


def _owned(
    provider: ConfigProvider, owned: Mapping[type, str], inactive: Mapping[type, str]
) -> ConfigProvider:
    _ = _owner(provider.config_type, provider.name, owned, inactive)
    return provider


def _owner(
    config_type: type, provider: str, owned: Mapping[type, str], inactive: Mapping[type, str]
) -> str:
    if config_type is NoConfig:
        raise ConfigProviderError(provider, "NoConfig is never configurable")
    owner = owned.get(config_type)
    if owner is None:
        raise UnknownConfigTypeError(provider, config_type, inactive.get(config_type))
    return owner


def _prepends(bundles: Sequence[AnyBundle], env: str) -> list[Prepend]:
    active = {type(b).metadata().name: type(b).metadata().config for b in bundles}
    recorded: list[Prepend] = []
    for bundle in bundles:
        source = type(bundle).metadata().name
        bundle.prepend(ConfigPrepender(env=env, source=source, active=active, prepends=recorded))
    return recorded


def _steps(
    bundle: str,
    config_type: type,
    providers: Sequence[ConfigProvider],
    given: Sequence[object],
    prepends: Sequence[Prepend],
) -> list[_Step]:
    """Return the steps resolving ``bundle``'s config, in the order they apply."""
    steps = _base(config_type, providers, given)
    steps.extend(
        _Step(f"prepend {prepend.source}", _checked(prepend, config_type))
        for prepend in prepends
        if prepend.target == bundle
    )
    transforms = [provider for provider in providers if provider.form == "transform"]
    for conditional in (False, True):
        # sorted() is stable: equal priorities keep scan order.
        group = sorted(
            (provider for provider in transforms if provider.conditional is conditional),
            key=lambda provider: -provider.priority,
        )
        steps.extend(_Step(f"transform {provider.name}", provider.apply) for provider in group)
    return steps


def _base(
    config_type: type, providers: Sequence[ConfigProvider], given: Sequence[object]
) -> list[_Step]:
    """Return the one base step, if any: the conditional group wins over the unconditional one.

    Raises:
        ConflictingConfigProvidersError: If either group has two.
    """
    bases = [provider for provider in providers if provider.form == "base"]
    conditional = [provider for provider in bases if provider.conditional]
    unconditional = [
        *(_Step(_STANDALONE, _replacing(value)) for value in given),
        *(
            _Step(f"base {provider.name}", provider.apply)
            for provider in bases
            if not provider.conditional
        ),
    ]
    for group in (
        [_Step(f"base {provider.name}", provider.apply) for provider in conditional],
        unconditional,
    ):
        if len(group) > 1:
            names = tuple(step.label.removeprefix("base ") for step in group)
            raise ConflictingConfigProvidersError(config_type, names)
    if conditional:
        return [_Step(f"base {conditional[0].name}", conditional[0].apply)]
    return unconditional[:1]


def _replacing(value: object) -> Callable[[object], object]:
    def replace(_current: object) -> object:
        return value

    return replace


def _checked(prepend: Prepend, config_type: type) -> Callable[[object], object]:
    """Return ``prepend``'s transform, refusing a result that is not a ``config_type``."""
    provider = f"prepend by bundle {prepend.source}"

    def apply(current: object) -> object:
        try:
            produced = prepend.fn(current)
        except Exception as error:
            error.add_note(f"raised by {provider} ({prepend.description})")
            raise
        if not isinstance(produced, config_type):
            reason = f"returned {type(produced).__qualname__}, not {config_type.__qualname__}"
            raise ConfigProviderError(provider, reason)
        return produced

    return apply
