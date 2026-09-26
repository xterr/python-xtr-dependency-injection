"""Loading every bundle's extension into the container: the first pass the compiler runs.

In order, for the active bundles:

1. every bundle's ``prepend_extension``, recording config prepends;
2. every bundle's config resolved — default, application base provider,
   ``alias_of`` forwards, prepends, application transforms — then its
   ``%name%`` parameter references (``%env(...)%`` among them);
3. every bundle's ``load_extension`` with its resolved config — right after the
   kernel bundle, every resolved config is registered under its type;
4. the late scan of what bundles asked to scan while loading;
5. a definition for every scanned ``@as_service`` / ``@as_alias`` object.

The application's marked services come last, so wherever they override a
bundle's service the report says so, and collections list bundles first.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast, final

from xtr_dependency_injection.builder._origins import origin_of, scanned_origin
from xtr_dependency_injection.builder.conflict_policy import record_alias
from xtr_dependency_injection.builder.container_builder import ContainerBuilder
from xtr_dependency_injection.builder.definition import Definition, Origin
from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator
from xtr_dependency_injection.bundle import KERNEL_BUNDLE, NoConfig
from xtr_dependency_injection.config.config_resolver import resolve_configs
from xtr_dependency_injection.decorator.as_alias import aliases_of
from xtr_dependency_injection.decorator.as_service import service_of
from xtr_dependency_injection.decorator.as_tagged_item import tagged_item_of
from xtr_dependency_injection.decorator.remove_if_missing import (
    REMOVE_IF_MISSING_TAG,
)
from xtr_dependency_injection.decorator.remove_if_missing import (
    markers_of as remove_if_missing_markers_of,
)
from xtr_dependency_injection.scan.scanner import ScanResult

from ._state import state_of
from ._wireup_bridge import key_type

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from xtr_dependency_injection.builder.definition import ServiceKey
    from xtr_dependency_injection.builder.service_configurator import BuildState
    from xtr_dependency_injection.bundle.bundle import AnyBundle
    from xtr_dependency_injection.diagnostics.report import ReportBuilder
    from xtr_dependency_injection.scan.scanned_object import ScannedObject
    from xtr_dependency_injection.scan.scanner import Scanner

__all__ = ["MergeExtensionConfigurationPass"]


@final
class MergeExtensionConfigurationPass:
    """Prepends, resolves and loads every bundle's configuration, then the marked services.

    Attributes:
        late: What the late scan found, once the pass has run — the kernel
            reads its lifecycle hooks.
    """

    __slots__ = ("_bundles", "_early", "_given", "_inactive", "_report", "_scanner", "late")

    def __init__(  # noqa: PLR0913 — every input feeds the merge directly.
        self,
        *,
        bundles: Sequence[AnyBundle],
        early: ScanResult,
        scanner: Scanner,
        inactive: Mapping[type, str],
        report: ReportBuilder,
        given: Sequence[object] = (),
    ) -> None:
        """Merge ``bundles``, reading configure providers and marked objects from ``early``.

        Args:
            bundles: The active bundles, in dependency order.
            early: What the early scan found.
            scanner: The scanner to run the late scan with.
            inactive: Config type to bundle name, for listed but
                environment-disabled bundles.
            report: Where the config and scan decisions are recorded.
            given: Config values handed in directly, each the base config of
                the bundle declaring its type.
        """
        self._bundles = tuple(bundles)
        self._early = early
        self._scanner = scanner
        self._inactive = inactive
        self._report = report
        self._given = tuple(given)
        self.late = ScanResult()

    def process(self, builder: ContainerBuilder) -> None:
        """Run the five steps of the merge, leaving the builder in phase ``process``."""
        state = state_of(builder)
        # A bundle without a config resolves to ``NoConfig`` whatever happens, so it
        # is known before the prepends run, and ``prepend_extension_config`` can
        # refuse to target one.
        state.configs = {
            _origin(bundle).name: NoConfig()
            for bundle in self._bundles
            if type(bundle).metadata().config is NoConfig
        }
        state.phase = "prepend"
        for bundle in self._bundles:
            bundle.prepend_extension(ContainerBuilder(state, _origin(bundle)))
        configs = resolve_configs(
            bundles=self._bundles,
            providers=self._early.configure,
            inactive=self._inactive,
            given=self._given,
            prepends=state.prepends,
        )
        bag = state.parameter_bag
        values = {
            name: bag.unescape_value(bag.resolve_value(value))
            for name, value in configs.values.items()
        }
        self._report.configs.extend(
            replace(report, value=values[report.bundle]) for report in configs.reports
        )
        self._report.skipped.extend(configs.skipped)
        state.configs = values
        state.phase = "load"
        for bundle in self._bundles:
            origin = _origin(bundle)
            name = origin.name
            services = ServiceConfigurator(state, origin)
            bundle.load_extension(values[name], services, ContainerBuilder(state, origin))
            if name == KERNEL_BUNDLE:
                _register_configs(state, values)
        for owner, resources in state.late_scans:
            self.late.extend(self._scanner.scan(resources, owner=owner, late=True))
        state.candidates.extend(self.late.services)
        state.scanned_decorators.extend(self.late.decorators)
        _register_marked(state, [*self._early.marked, *self.late.marked])
        # The compiler runs every later pass in phase ``process``.
        state.phase = "process"


def _origin(bundle: AnyBundle) -> Origin:
    return origin_of(type(bundle).metadata().name)


def _register_configs(state: BuildState, values: Mapping[str, object]) -> None:
    """Register every resolved non-``NoConfig`` config under its type, as the kernel."""
    services = ServiceConfigurator(state, origin_of(KERNEL_BUNDLE))
    for value in values.values():
        if not isinstance(value, NoConfig):
            _ = services.instance(value)


def _register_marked(state: BuildState, marked: Sequence[ScannedObject]) -> None:
    """Define every object carrying ``@as_service`` or ``@as_alias``.

    Each object becomes exactly one definition under its own type and
    qualifier; every ``@as_alias(Iface)`` records an alias
    ``(Iface, qualifier) -> (own type, own qualifier)``.
    """
    for scanned in marked:
        obj = scanned.obj
        if inspect.isclass(obj):
            own_type = obj
            kind: Literal["class", "factory"] = "class"
        elif inspect.isfunction(obj):
            own_type = key_type(cast("Callable[..., object]", obj))
            kind = "factory"
        else:  # pragma: no cover — the scanner queues only classes and functions.
            continue
        service = service_of(obj)
        lifetime = service.lifetime if service is not None else "singleton"
        own_key: ServiceKey = (own_type, service.qualifier if service is not None else None)
        origin = scanned_origin(scanned, "marked by")
        existing = state.store.get(own_key)
        if existing is None or existing.provider is not obj:
            definition = Definition(own_key, obj, kind, lifetime, origin)
            tagged = tagged_item_of(obj)
            if tagged is not None:
                definition.priority = tagged.priority
                definition.before = tagged.before
                definition.after = tagged.after
            state.store.add(definition)
        for marker in aliases_of(obj):
            record_alias(
                state.aliases,
                state.alias_origins,
                (marker.alias, marker.qualifier),
                own_key,
                origin,
            )
        # ``add`` keeps a definition under ``own_key`` whoever wins the key.
        definition = state.store.get(own_key)
        if definition is not None:  # pragma: no branch
            for attributes in remove_if_missing_markers_of(obj):
                _ = definition.add_tag(REMOVE_IF_MISSING_TAG, **attributes)
