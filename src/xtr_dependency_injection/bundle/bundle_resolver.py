"""Choosing which bundles a build activates, and in what order.

Applications list root bundles in ``<package>/bundles.py`` as
``BUNDLES = {LoggingBundle: {"all": True}, DebugBundle: {"dev": True}}``; the
resolver starts from that mapping (plus the always-active ``KernelBundle``)
and walks each active bundle's ``@required_bundle`` declarations recursively,
importing string targets lazily. Only active bundle classes are instantiated
(lazy instantiation: a disabled bundle's class is never constructed).
Every bundle considered — active, disabled by the environment or skipped for
an invalid ``ignore_on_invalid`` target — is reported.
"""

from __future__ import annotations

import heapq
import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from xtr_dependency_injection.diagnostics import BundleReport
from xtr_dependency_injection.exception import (
    BundleDefinitionError,
    CircularBundleDependencyError,
    DuplicateBundleError,
    MissingBundleError,
)
from xtr_dependency_injection.exception._naming import qualified_name

from .bundle import KERNEL_BUNDLE, METADATA_ATTRIBUTE, AnyBundle, Bundle, NoConfig
from .bundle_metadata import BundleMetadata

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .required_bundle import RequiredBundle

__all__ = ["ResolvedBundles", "resolve_bundles"]

Source = Literal["kernel", "listed", "required"]
State = Literal["active", "skipped", "env_disabled"]


@dataclass(frozen=True, slots=True)
class ResolvedBundles:
    """The active bundles in dependency order, and a report on every bundle considered.

    Attributes:
        bundles: Active bundle instances; the kernel bundle first, then each
            bundle after the ones it requires.
        reports: One per bundle considered: active ones in order, then the
            rest by name.
    """

    bundles: tuple[AnyBundle, ...]
    reports: tuple[BundleReport, ...]


@dataclass(slots=True)
class _Candidate:
    bundle_type: type[AnyBundle]
    metadata: BundleMetadata
    qualname: str
    source: Source
    active: bool
    state: State = "active"
    reason: str | None = None
    required_names: list[str] = field(default_factory=list)


def resolve_bundles(
    *,
    core: AnyBundle,
    listed: Mapping[type[AnyBundle], Mapping[str, bool]],
    env: str,
) -> ResolvedBundles:
    """Return the bundles active in ``env``, ordered, with a report on each.

    Args:
        core: The ``kernel`` bundle; always active and always first.
        listed: The bundles the application declared in ``bundles.py``, mapped
            to their per-environment activity flags.
        env: The environment being built.

    Raises:
        DuplicateBundleError: If two different classes share one bundle name.
        MissingBundleError: If a required bundle cannot be imported (and its
            declaration is not ``ignore_on_invalid``).
        BundleDefinitionError: If a required class is not a decorated
            :class:`Bundle`, or two active bundles share a non-``NoConfig``
            config type, or a listed bundle raises when instantiated.
        CircularBundleDependencyError: If the required graph loops.
    """
    candidates: dict[str, _Candidate] = {}
    _ = _register_class(candidates, type(core), source="kernel", active=True)
    for bundle_type, flags in listed.items():
        active = _is_active_in(env, flags)
        _ = _register_class(candidates, bundle_type, source="listed", active=active)
    _close_over_required(candidates)
    for candidate in candidates.values():
        if not candidate.active and candidate.state == "active":
            candidate.state = "env_disabled"
            candidate.reason = f"not active in {env!r}"
    active = {name: c for name, c in candidates.items() if c.state == "active"}
    _check_config_types(active)
    order = _topological_order(active)
    bundles = tuple(_instance(active[name], core) for name in order)
    reports = (
        *(_report(active[name]) for name in order),
        *(
            _report(candidate)
            for _, candidate in sorted(candidates.items())
            if candidate.state != "active"
        ),
    )
    return ResolvedBundles(bundles, reports)


def _is_active_in(env: str, flags: Mapping[str, bool]) -> bool:
    """Return whether ``flags`` activates the bundle for ``env`` — env then ``all``."""
    if env in flags:
        return flags[env]
    return flags.get("all", False)


def _register_class(
    candidates: dict[str, _Candidate],
    bundle_type: type[AnyBundle],
    *,
    source: Source,
    active: bool,
) -> _Candidate:
    """Add ``bundle_type`` to ``candidates`` (or return an existing entry) after validating it."""
    if METADATA_ATTRIBUTE not in vars(bundle_type):
        raise BundleDefinitionError(
            qualified_name(bundle_type), "it is not decorated with @as_bundle"
        )
    metadata = bundle_type.metadata()
    name = metadata.name
    existing = candidates.get(name)
    if existing is not None:
        if existing.bundle_type is not bundle_type:
            raise DuplicateBundleError(name, existing.qualname, qualified_name(bundle_type))
        # Same class listed and pulled in as required — keep the stronger source.
        if source == "listed":
            existing.source = "listed"
            existing.active = existing.active or active
        return existing
    candidates[name] = _Candidate(
        bundle_type=bundle_type,
        metadata=metadata,
        qualname=qualified_name(bundle_type),
        source=source,
        active=active,
    )
    return candidates[name]


def _close_over_required(candidates: dict[str, _Candidate]) -> None:
    """Walk ``@required_bundle`` declarations from every active candidate."""
    visited: set[str] = set()
    pending = [candidate for candidate in candidates.values() if candidate.active]
    while pending:
        requirer = pending.pop()
        if requirer.metadata.name in visited:
            continue
        visited.add(requirer.metadata.name)
        for declaration in requirer.metadata.required:
            resolved = _resolve_target(declaration, requirer)
            if resolved is None:
                # Skipped with ignore_on_invalid; record as a report entry.
                _record_skipped(candidates, declaration, requirer)
                continue
            bundle_type = resolved
            candidate = _register_from_required(candidates, bundle_type, requirer)
            if candidate.metadata.name not in requirer.required_names:
                requirer.required_names.append(candidate.metadata.name)
            if requirer.active and not candidate.active:
                # Required bundles inherit the requirer's activity.
                candidate.active = True
            if candidate.active and candidate.metadata.name not in visited:
                pending.append(candidate)


def _resolve_target(declaration: RequiredBundle, requirer: _Candidate) -> type[AnyBundle] | None:
    """Return the target of ``declaration``; ``None`` when ``ignore_on_invalid`` swallows it."""
    target = declaration.target
    if isinstance(target, type):
        # The annotation restricts type targets to Bundle subclasses, but an
        # untyped caller may still pass a non-Bundle: keep the runtime check.
        if not issubclass(target, Bundle):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise BundleDefinitionError(
                qualified_name(target),
                f"required by {requirer.metadata.name}: it is not a Bundle subclass",
            )
        return target
    module_name, _, class_name = target.partition(":")
    try:
        module = importlib.import_module(module_name)
        loaded = cast("object", getattr(module, class_name))
    except (ImportError, AttributeError) as error:
        if declaration.ignore_on_invalid:
            return None
        raise MissingBundleError(target, requirer.metadata.name, str(error)) from error
    if not (isinstance(loaded, type) and issubclass(loaded, Bundle)):
        raise BundleDefinitionError(
            target,
            f"required by {requirer.metadata.name}: {target} is not a Bundle subclass",
        )
    return cast("type[AnyBundle]", loaded)


def _register_from_required(
    candidates: dict[str, _Candidate],
    bundle_type: type[AnyBundle],
    requirer: _Candidate,
) -> _Candidate:
    """Register a required bundle; if already listed, keep its own listed activity."""
    if METADATA_ATTRIBUTE not in vars(bundle_type):
        raise BundleDefinitionError(
            qualified_name(bundle_type),
            f"required by {requirer.metadata.name}: it is not decorated with @as_bundle",
        )
    metadata = bundle_type.metadata()
    existing = candidates.get(metadata.name)
    if existing is not None:
        if existing.bundle_type is not bundle_type:
            raise DuplicateBundleError(
                metadata.name, existing.qualname, qualified_name(bundle_type)
            )
        return existing
    candidates[metadata.name] = _Candidate(
        bundle_type=bundle_type,
        metadata=metadata,
        qualname=qualified_name(bundle_type),
        source="required",
        active=False,
    )
    return candidates[metadata.name]


def _record_skipped(
    candidates: dict[str, _Candidate],
    declaration: RequiredBundle,
    requirer: _Candidate,
) -> None:
    """Record an ``ignore_on_invalid`` target as a skipped report entry."""
    target = declaration.target
    name = target if isinstance(target, str) else qualified_name(target)
    key = f"__skipped__:{name}"
    if key in candidates:
        return
    metadata_stub = BundleMetadata(name=key, config=NoConfig)
    candidates[key] = _Candidate(
        bundle_type=cast("type[AnyBundle]", Bundle),
        metadata=metadata_stub,
        qualname=name,
        source="required",
        active=False,
        state="skipped",
        reason=f"required by {requirer.metadata.name}, missing (ignore_on_invalid)",
    )


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
    """Return ``active``'s names, each after its active required bundles, ``kernel`` first."""
    dependencies = {
        name: {req for req in candidate.required_names if req in active}
        for name, candidate in active.items()
    }
    dependents: dict[str, set[str]] = {name: set() for name in active}
    for name, needs in dependencies.items():
        for dependency in needs:
            dependents[dependency].add(name)
    remaining = {name: len(needs) for name, needs in dependencies.items()}
    ready = [(name != KERNEL_BUNDLE, name) for name, count in remaining.items() if count == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        _, name = heapq.heappop(ready)
        order.append(name)
        for dependent in dependents[name]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                heapq.heappush(ready, (dependent != KERNEL_BUNDLE, dependent))
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


def _instance(candidate: _Candidate, core: AnyBundle) -> AnyBundle:
    """Instantiate one active candidate, reusing ``core`` for the kernel bundle."""
    if candidate.source == "kernel":
        return core
    try:
        return candidate.bundle_type()
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
        required=tuple(candidate.required_names),
    )
