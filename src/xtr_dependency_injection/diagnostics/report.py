"""What the kernel did, as data: bundles, configs, definitions and the scan.

Every build records its decisions here as it goes — which bundle came from
where and why one was skipped, each step a config went through, which
definition overrode which — so ``debug:*`` commands and error messages can
show them without re-deriving anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from xtr_dependency_injection.builder.definition import Lifetime, Origin, ServiceKey
from xtr_dependency_injection.exception._naming import key_name

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "BundleReport",
    "ConfigReport",
    "DefinitionReport",
    "KernelReport",
    "ReportBuilder",
    "ScanReport",
]

Section = Literal["bundles", "configs", "definitions", "scan"]


@dataclass(frozen=True, slots=True)
class BundleReport:
    """One bundle the kernel considered, and what it decided about it.

    Attributes:
        name: The bundle's name.
        qualname: ``module:QualName`` of its class, or the entry point's
            value when it could not be loaded.
        source: ``"discovered"``, ``"explicit"`` or ``"required"``.
        state: ``"active"``, ``"skipped"``, ``"excluded"`` or
            ``"env_disabled"``.
        reason: Why it is not active, when it is not.
        requires: The bundles it requires.
        optional: The bundles it orders itself after, when active.
    """

    name: str
    qualname: str
    source: Literal["discovered", "explicit", "required"]
    state: Literal["active", "skipped", "excluded", "env_disabled"]
    reason: str | None = None
    requires: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConfigReport:
    """One bundle's resolved config and every step that produced it.

    Attributes:
        bundle: The bundle's name.
        value: The resolved config.
        steps: Its provenance, in order: ``"default"``,
            ``"base app.config.logging:logging"``, ``"prepend messenger"``…
    """

    bundle: str
    value: object
    steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DefinitionReport:
    """One compiled definition: what provides it, who contributed it, who it displaced.

    Attributes:
        key: The type and qualifier it is provided under.
        provider_qualname: Name of the class, factory or instance type.
        kind: ``"class"``, ``"factory"``, ``"instance"`` or ``"declared"``.
        lifetime: How long wireup keeps what it builds.
        origin: Who contributed it.
        overrides: The origins of the definitions it replaced.
        decorated_by: The decorators wrapping it, innermost first.
    """

    key: ServiceKey
    provider_qualname: str
    kind: Literal["class", "factory", "instance", "declared"]
    lifetime: Lifetime
    origin: Origin
    overrides: tuple[Origin, ...] = ()
    decorated_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScanReport:
    """The modules scanned, and every object an environment condition dropped.

    Attributes:
        modules: Every module imported by the scan, in import order.
        skipped: ``(qualname, reason)`` for each object left out.
    """

    modules: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class KernelReport:
    """Everything one build decided, frozen when its container is compiled."""

    bundles: tuple[BundleReport, ...] = ()
    configs: tuple[ConfigReport, ...] = ()
    definitions: tuple[DefinitionReport, ...] = ()
    scan: ScanReport = field(default_factory=ScanReport)

    def render(self, section: Section | None = None) -> str:
        """Return the report as plain-text tables: one section, or all of them.

        Fixed columns, no colours, nothing but the standard library — so the
        same text serves a terminal, a log line and an exception note.
        """
        renderers = {
            "bundles": self._bundles,
            "configs": self._configs,
            "definitions": self._definitions,
            "scan": self._scan,
        }
        chosen = (section,) if section is not None else tuple(renderers)
        return "\n\n".join(renderers[name]() for name in chosen)

    def _bundles(self) -> str:
        rows = [
            (
                bundle.name,
                bundle.source,
                bundle.state,
                ", ".join(bundle.requires) or "-",
                ", ".join(bundle.optional) or "-",
                bundle.qualname,
                bundle.reason or "",
            )
            for bundle in self.bundles
        ]
        headers = ("Name", "Source", "State", "Requires", "Optional", "Class", "Reason")
        return _titled("Bundles", _table(headers, rows))

    def _configs(self) -> str:
        rows = [
            (config.bundle, " -> ".join(config.steps), repr(config.value))
            for config in self.configs
        ]
        return _titled("Configs", _table(("Bundle", "Steps", "Value"), rows))

    def _definitions(self) -> str:
        rows = [
            (
                key_name(definition.key),
                definition.provider_qualname,
                definition.kind,
                definition.lifetime,
                str(definition.origin),
                ", ".join(str(origin) for origin in definition.overrides) or "-",
                ", ".join(definition.decorated_by) or "-",
            )
            for definition in self.definitions
        ]
        headers = ("Service", "Provider", "Kind", "Lifetime", "Origin", "Overrides", "Decorated by")
        return _titled("Definitions", _table(headers, rows))

    def _scan(self) -> str:
        modules = _table(("Module",), [(module,) for module in self.scan.modules])
        skipped = _table(("Skipped", "Reason"), list(self.scan.skipped))
        return _titled("Scan", f"{modules}\n\n{skipped}")


@dataclass(slots=True)
class ReportBuilder:
    """Collects a report while the kernel builds; frozen at the end of compilation."""

    bundles: list[BundleReport] = field(default_factory=list)
    configs: list[ConfigReport] = field(default_factory=list)
    definitions: list[DefinitionReport] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def freeze(self) -> KernelReport:
        """Return what was collected as an immutable report."""
        return KernelReport(
            bundles=tuple(self.bundles),
            configs=tuple(self.configs),
            definitions=tuple(self.definitions),
            scan=ScanReport(modules=tuple(self.modules), skipped=tuple(self.skipped)),
        )


def _titled(title: str, body: str) -> str:
    return f"{title}\n{'=' * len(title)}\n{body}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Return ``rows`` under ``headers``, each column as wide as its widest cell."""
    if not rows:
        return f"{'  '.join(headers)}\n(none)"
    widths = [
        max(len(headers[column]), *(len(row[column]) for row in rows))
        for column in range(len(headers))
    ]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(
            cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
        ).rstrip()

    rule = "  ".join("-" * width for width in widths)
    return "\n".join([line(headers), rule, *(line(row) for row in rows)])
