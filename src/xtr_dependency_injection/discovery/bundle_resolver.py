"""Choosing the active bundles and their order.

From what was discovered (or listed), the resolver adds every bundle
required, drops the excluded and those disabled in this environment, checks
that everything required is still there, and orders the rest so each bundle
comes after what it depends on. Every decision is reported, the reason
included.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.bundle.bundle import AnyBundle
from xtr_dependency_injection.bundle.bundle_metadata import BundleMetadata
from xtr_dependency_injection.diagnostics import BundleReport
from xtr_dependency_injection.exception import (
    BundleDefinitionError,
    CircularBundleDependencyError,
    DuplicateBundleError,
    MissingBundleError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from .bundle_discovery import DiscoveredBundle

__all__ = ["ResolvedBundles", "resolve_bundles"]

Source = Literal["discovered", "explicit", "required"]
State = Literal["active", "skipped", "excluded", "env_disabled"]


@dataclass(frozen=True, slots=True)
class ResolvedBundles:
    """The active bundles in dependency order, and a report on every bundle considered.

    Attributes:
        bundles: Active bundle instances; the core bundle first, then each
            bundle after everything it requires or optionally follows.
        reports: One per bundle considered: active ones in order, then the
            rest by name.
    """

    bundles: tuple[AnyBundle, ...]
    reports: tuple[BundleReport, ...]


@dataclass(slots=True)
class _Candidate:
    metadata: BundleMetadata
    qualname: str
    source: Source
    bundle: AnyBundle | None = None
    bundle_type: type[AnyBundle] | None = None
    state: State = "active"
    reason: str | None = None


def resolve_bundles(  # noqa: PLR0913 — each input is a separate Kernel argument.
    *,
    core: AnyBundle,
    discovered: Sequence[DiscoveredBundle],
    explicit: Sequence[AnyBundle] | None,
    exclude: Iterable[str],
    bundle_envs: Mapping[str, Iterable[str]] | None,
    env: str,
) -> ResolvedBundles:
    """Return the bundles active in ``env``, ordered, with a report on each.

    Args:
        core: The ``kernel`` bundle; always active and always first.
        discovered: What discovery found. With ``explicit`` given, only
            used to resolve ``requires``.
        explicit: The bundles the application listed, or ``None`` for every
            discovered one.
        exclude: Names to leave out.
        bundle_envs: Per-name environments, overriding a bundle's own.
        env: The environment being built.

    Raises:
        MissingBundleError: If a required bundle is absent, skipped,
            excluded or disabled in ``env``.
        DuplicateBundleError: If two listed bundles share a name.
        CircularBundleDependencyError: If dependencies loop.
        BundleDefinitionError: If a bundle cannot be built with no
            arguments, the core bundle is excluded, or two active bundles
            share a config type.
    """
    available = {entry.name: entry for entry in discovered}
    candidates, skipped = _select(core, discovered, explicit)
    _close_over_requires(candidates, available)
    _filter(candidates, set(exclude), bundle_envs or {}, env)
    active = {
        name: candidate for name, candidate in candidates.items() if candidate.state == "active"
    }
    _check_requires(active, candidates)
    _check_config_types(active)
    order = _topological_order(active)
    bundles = tuple(_instance(active[name]) for name in order)
    reports = (
        *(_report(active[name]) for name in order),
        *(
            _report(candidate)
            for _, candidate in sorted({**skipped, **candidates}.items())
            if candidate.state != "active"
        ),
    )
    return ResolvedBundles(bundles, reports)


def _select(
    core: AnyBundle,
    discovered: Sequence[DiscoveredBundle],
    explicit: Sequence[AnyBundle] | None,
) -> tuple[dict[str, _Candidate], dict[str, _Candidate]]:
    """Return the starting candidates by name, and the discovered entries that were skipped."""
    core_metadata = type(core).metadata()
    candidates = {core_metadata.name: _listed(core, "explicit")}
    skipped: dict[str, _Candidate] = {}
    if explicit is None:
        for entry in discovered:
            if entry.bundle is None:
                skipped[entry.name] = _skipped_entry(entry)
            else:
                candidates[entry.name] = _discovered(entry.bundle, "discovered")
        return candidates, skipped
    for bundle in explicit:
        candidate = _listed(bundle, "explicit")
        name = candidate.metadata.name
        if name in candidates:
            raise DuplicateBundleError(name, candidates[name].qualname, candidate.qualname)
        candidates[name] = candidate
    return candidates, skipped


def _close_over_requires(
    candidates: dict[str, _Candidate], available: Mapping[str, DiscoveredBundle]
) -> None:
    """Add every bundle required, recursively, from what was discovered."""
    pending = list(candidates.values())
    while pending:
        requirer = pending.pop()
        for name in requirer.metadata.requires:
            if name in candidates:
                continue
            entry = available.get(name)
            if entry is None or entry.bundle is None:
                reason = entry.reason if entry is not None else None
                raise MissingBundleError(name, requirer.metadata.name, reason)
            candidates[name] = _discovered(entry.bundle, "required")
            pending.append(candidates[name])


def _filter(
    candidates: dict[str, _Candidate],
    excluded: set[str],
    bundle_envs: Mapping[str, Iterable[str]],
    env: str,
) -> None:
    for name, candidate in candidates.items():
        if name in excluded:
            if name == "kernel":
                raise BundleDefinitionError(name, "the kernel bundle cannot be excluded")
            candidate.state, candidate.reason = "excluded", "listed in exclude_bundles"
            continue
        envs = bundle_envs.get(name, candidate.metadata.envs)
        if envs is not None and env not in set(envs):
            candidate.state = "env_disabled"
            candidate.reason = f"active only in: {', '.join(sorted(envs))}"


def _check_requires(active: Mapping[str, _Candidate], candidates: Mapping[str, _Candidate]) -> None:
    for candidate in active.values():
        for name in candidate.metadata.requires:
            if name not in active:
                reason = candidates[name].reason if name in candidates else None
                raise MissingBundleError(name, candidate.metadata.name, reason)


def _check_config_types(active: Mapping[str, _Candidate]) -> None:
    owners: dict[type[object], str] = {}
    for name, candidate in sorted(active.items()):
        config = candidate.metadata.config
        if config is NoConfig:
            continue
        if config in owners:
            owner = owners[config]
            reason = f"its config type {config.__qualname__} already belongs to bundle {owner!r}"
            raise BundleDefinitionError(name, reason)
        owners[config] = name


def _topological_order(active: Mapping[str, _Candidate]) -> list[str]:
    """Return ``active``'s names, each after its active dependencies, ``kernel`` first.

    Ties break by name, so the order never depends on discovery order.

    Raises:
        CircularBundleDependencyError: If the dependencies loop.
    """
    dependencies = {
        name: {
            dependency
            for dependency in (*candidate.metadata.requires, *candidate.metadata.optional)
            if dependency in active
        }
        for name, candidate in active.items()
    }
    dependents: dict[str, set[str]] = {name: set() for name in active}
    for name, needs in dependencies.items():
        for dependency in needs:
            dependents[dependency].add(name)
    remaining = {name: len(needs) for name, needs in dependencies.items()}
    ready = [(name != "kernel", name) for name, count in remaining.items() if count == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        _, name = heapq.heappop(ready)
        order.append(name)
        for dependent in dependents[name]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                heapq.heappush(ready, (dependent != "kernel", dependent))
    if len(order) < len(active):
        raise CircularBundleDependencyError(_cycle(dependencies, set(active) - set(order)))
    return order


def _cycle(dependencies: Mapping[str, set[str]], stuck: set[str]) -> tuple[str, ...]:
    """Return one loop among ``stuck``, its first bundle repeated at the end."""
    path: list[str] = []
    name = min(stuck)
    while name not in path:
        path.append(name)
        name = min(dependency for dependency in dependencies[name] if dependency in stuck)
    return (*path[path.index(name) :], name)


def _listed(bundle: AnyBundle, source: Source) -> _Candidate:
    bundle_type = type(bundle)
    return _Candidate(
        metadata=bundle_type.metadata(),
        qualname=_qualname(bundle_type),
        source=source,
        bundle=bundle,
        bundle_type=bundle_type,
    )


def _discovered(bundle_type: type[AnyBundle], source: Source) -> _Candidate:
    return _Candidate(
        metadata=bundle_type.metadata(),
        qualname=_qualname(bundle_type),
        source=source,
        bundle_type=bundle_type,
    )


def _skipped_entry(entry: DiscoveredBundle) -> _Candidate:
    return _Candidate(
        metadata=BundleMetadata(name=entry.name, config=NoConfig),
        qualname=entry.value,
        source="discovered",
        state="skipped",
        reason=entry.reason,
    )


def _instance(candidate: _Candidate) -> AnyBundle:
    if candidate.bundle is not None:
        return candidate.bundle
    bundle_type = candidate.bundle_type
    if bundle_type is None:  # pragma: no cover — only skipped entries lack a type
        raise MissingBundleError(candidate.metadata.name, None, candidate.reason)
    try:
        return bundle_type()
    except Exception as error:
        failure = BundleDefinitionError(
            candidate.metadata.name, "the bundle class cannot be built with no arguments"
        )
        raise failure from error


def _report(candidate: _Candidate) -> BundleReport:
    return BundleReport(
        name=candidate.metadata.name,
        qualname=candidate.qualname,
        source=candidate.source,
        state=candidate.state,
        reason=candidate.reason,
        requires=candidate.metadata.requires,
        optional=candidate.metadata.optional,
    )


def _qualname(bundle_type: type[AnyBundle]) -> str:
    return f"{bundle_type.__module__}:{bundle_type.__qualname__}"
