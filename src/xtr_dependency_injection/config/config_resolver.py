"""Resolving each bundle's config, one deterministic step at a time.

For every active bundle, in order:

1. its config type's default, ``C()``;
2. the application's base provider, if any — one conditional on the
   environment beats an unconditional one;
3. ``AliasOf`` forwards from other bundles, whose configs resolve first;
4. other bundles' prepends (recorded via
   ``builder.prepend_extension_config`` from ``Bundle.prepend_extension``),
   in call order;
5. the application's transforms — unconditional, then conditional; within
   each, by priority, highest first, then in scan order.

Every step is recorded, so ``debug:config`` shows where a value came from.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.diagnostics import ConfigReport
from xtr_dependency_injection.exception import (
    CircularBundleDependencyError,
    ConfigProviderError,
    ConflictingConfigProvidersError,
    UnknownConfigTypeError,
)

from .alias_of import alias_of_fields
from .config_provider import ConfigProvider, config_provider_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from xtr_dependency_injection.builder.service_configurator import Prepend
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
            active or is not owned by any known bundle.
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
    given: Sequence[object] = (),
    prepends: Sequence[Prepend] = (),
) -> ResolvedConfigs:
    """Return the config of every bundle in ``bundles``, resolved in order.

    Args:
        bundles: The active bundles, in dependency order.
        providers: The ``@configure`` functions the early scan found.
        inactive: Config types of bundles that are not active, by type, for
            a clearer error.
        given: Config values acting as unconditional base providers — how
            standalone ``injectables()`` receives its configs.
        prepends: What bundles recorded via ``prepend_extension``.

    Raises:
        UnknownConfigTypeError: If a provider or given config targets a type
            no active bundle owns.
        ConflictingConfigProvidersError: If one group has two base
            providers.
        ConfigProviderError: If a provider or prepend returns the wrong type.
    """
    owned = {type(bundle).metadata().config: type(bundle).metadata().name for bundle in bundles}
    active_by_name = {type(bundle).metadata().name: bundle for bundle in bundles}
    parsed = [
        config_provider_of(cast("Callable[..., object]", scanned.obj)) for scanned in providers
    ]
    for provider in parsed:
        _ = _owner(provider.config_type, provider.name, owned, inactive)
    for value in given:
        _ = _owner(type(value), _STANDALONE, owned, inactive)
    resolved_prepends = _resolve_prepends(prepends, owned)
    alias_edges, skipped_aliases = _resolve_alias_edges(bundles, active_by_name)
    values: dict[str, object] = {}
    reports: dict[str, ConfigReport] = {}
    pending_alias: dict[str, list[_Step]] = {}
    for bundle in _resolution_order(bundles, alias_edges):
        metadata = type(bundle).metadata()
        config_type = metadata.config
        alias_steps = pending_alias.pop(metadata.name, [])
        steps = (
            _steps(
                metadata.name,
                config_type,
                [provider for provider in parsed if provider.config_type is config_type],
                [value for value in given if type(value) is config_type],
                resolved_prepends,
                alias_steps,
            )
            if config_type is not NoConfig
            else []
        )
        value: object = config_type()
        for step in steps:
            value = step.apply(value)
        values[metadata.name] = value
        reports[metadata.name] = ConfigReport(
            metadata.name, value, ("default", *(s.label for s in steps))
        )
        if config_type is not NoConfig:
            _queue_alias_forwards(
                owner=metadata.name,
                value=value,
                edges=alias_edges,
                pending=pending_alias,
            )
    skipped = (
        *(
            (
                f"{prepend.description} (prepend by bundle {prepend.source})",
                "target bundle is not active",
            )
            for prepend, target_name in resolved_prepends
            if target_name is None
        ),
        *skipped_aliases,
    )
    ordered = tuple(reports[type(bundle).metadata().name] for bundle in bundles)
    return ResolvedConfigs(values, ordered, skipped)


def _owner(
    config_type: type, provider: str, owned: Mapping[type, str], inactive: Mapping[type, str]
) -> str:
    if config_type is NoConfig:
        raise ConfigProviderError(provider, "NoConfig is never configurable")
    owner = owned.get(config_type)
    if owner is None:
        raise UnknownConfigTypeError(provider, config_type, inactive.get(config_type))
    return owner


def _resolve_prepends(
    prepends: Sequence[Prepend], owned: Mapping[type, str]
) -> list[tuple[Prepend, str | None]]:
    """Resolve every prepend's target to an active bundle name, or ``None`` when inactive."""
    resolved: list[tuple[Prepend, str | None]] = []
    for prepend in prepends:
        target = prepend.target
        if isinstance(target, str):
            name = target if target in owned.values() else None
        else:
            name = owned.get(target)
            if name is None:
                # Unknown type owned by no active bundle: raise here so the source is named.
                raise ConfigProviderError(
                    f"prepend by bundle {prepend.source}",
                    f"no active bundle owns config type {target.__qualname__}",
                )
        resolved.append((prepend, name))
    return resolved


def _steps(  # noqa: PLR0913, PLR0917 — one call assembles every ordered step for one bundle.
    bundle: str,
    config_type: type,
    providers: Sequence[ConfigProvider],
    given: Sequence[object],
    prepends: Sequence[tuple[Prepend, str | None]],
    alias_steps: Sequence[_Step],
) -> list[_Step]:
    """Return the steps resolving ``bundle``'s config, in the order they apply."""
    steps = _base(config_type, providers, given)
    if len(alias_steps) > 1:
        raise ConflictingConfigProvidersError(
            config_type, tuple(step.label for step in alias_steps)
        )
    if steps and alias_steps:
        base_label = steps[0].label.removeprefix("base ")
        raise ConflictingConfigProvidersError(config_type, (base_label, alias_steps[0].label))
    steps.extend(alias_steps)
    steps.extend(
        _Step(f"prepend {prepend.source}", _checked(prepend, config_type))
        for prepend, target_name in prepends
        if target_name == bundle
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


def _resolve_alias_edges(
    bundles: Sequence[AnyBundle], active_by_name: Mapping[str, AnyBundle]
) -> tuple[tuple[tuple[str, str, str, type], ...], tuple[tuple[str, str], ...]]:
    """Return (active alias edges, skipped entries) for the active bundle set.

    Each edge is ``(owner, target, field, target_config_type)``. An owner
    field pointing at an inactive bundle produces a skipped entry.
    """
    edges: list[tuple[str, str, str, type]] = []
    skipped: list[tuple[str, str]] = []
    for bundle in bundles:
        metadata = type(bundle).metadata()
        if metadata.config is NoConfig:
            continue
        for field_name, target in alias_of_fields(metadata.config):
            label = f"alias_of {metadata.name}.{field_name}"
            target_bundle = active_by_name.get(target)
            if target_bundle is None:
                skipped.append((label, "target bundle is not active"))
                continue
            target_config_type = type(target_bundle).metadata().config
            if target_config_type is NoConfig:
                raise ConfigProviderError(label, "target bundle has no config to alias to")
            edges.append((metadata.name, target, field_name, target_config_type))
    return tuple(edges), tuple(skipped)


def _resolution_order(
    bundles: Sequence[AnyBundle], edges: Sequence[tuple[str, str, str, type]]
) -> list[AnyBundle]:
    """Return ``bundles`` reordered so every alias owner resolves before its target.

    A bundle's config does not depend on the bundles it requires, only on the
    bundles forwarding into it, so the bundle order is kept wherever an alias
    edge does not ask otherwise: among the bundles ready to resolve, the one
    earliest in bundle order goes first.

    Raises:
        CircularBundleDependencyError: If the alias edges loop, a bundle
            aliasing to itself included.
    """
    names = [type(bundle).metadata().name for bundle in bundles]
    position = {name: index for index, name in enumerate(names)}
    owners: dict[str, set[str]] = {name: set() for name in names}
    for owner, target, _, _ in edges:
        owners[target].add(owner)
    order: list[AnyBundle] = []
    ready = [index for index, name in enumerate(names) if not owners[name]]
    heapq.heapify(ready)
    waiting = {name: len(forwarders) for name, forwarders in owners.items()}
    while ready:
        index = heapq.heappop(ready)
        order.append(bundles[index])
        for owner, target, _, _ in edges:
            if owner == names[index]:
                waiting[target] -= 1
                if waiting[target] == 0:
                    heapq.heappush(ready, position[target])
    if len(order) < len(bundles):
        stuck = {name for name, count in waiting.items() if count > 0}
        raise CircularBundleDependencyError(_alias_cycle(owners, stuck))
    return order


def _alias_cycle(owners: Mapping[str, set[str]], stuck: set[str]) -> tuple[str, ...]:
    """Return one alias loop among ``stuck``, its first bundle repeated at the end."""
    path: list[str] = []
    name = min(stuck)
    while name not in path:
        path.append(name)
        name = min(owner for owner in owners[name] if owner in stuck)
    return (*path[path.index(name) :], name)


def _queue_alias_forwards(
    *,
    owner: str,
    value: object,
    edges: Sequence[tuple[str, str, str, type]],
    pending: dict[str, list[_Step]],
) -> None:
    """Record ``owner``'s non-``None`` aliased field values as steps for their targets."""
    for edge_owner, target, field, target_config_type in edges:
        if edge_owner != owner:
            continue
        forwarded: object = getattr(value, field, None)
        if forwarded is None:
            continue
        if not isinstance(forwarded, target_config_type):
            raise ConfigProviderError(
                f"alias_of {owner}.{field}",
                f"returned {type(forwarded).__qualname__}, not {target_config_type.__qualname__}",
            )
        pending.setdefault(target, []).append(
            _Step(f"alias_of {owner}.{field}", _replacing(forwarded))
        )


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
