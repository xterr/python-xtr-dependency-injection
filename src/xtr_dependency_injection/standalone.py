"""Bundles without a kernel: plain wireup, and ``injectables()``.

For an application that builds its own wireup container, ``injectables()``
runs the same pipeline the kernel does — requirements, configs, load,
autoconfigure, process — without discovering anything and without scanning
an application package, and returns what to spread into
``create_async_container(injectables=[...])``::

    container = wireup.create_async_container(
        injectables=[
            app.services,
            *injectables([LoggingBundle(), MessengerBundle()], configs=[LOGGING, MESSENGER]),
        ],
    )

Boot and shutdown hooks do not run: nothing here owns the container's life.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from xtr_dependency_injection.compiler.wireup_compiler import emission_order, emit_injectables
from xtr_dependency_injection.diagnostics.report import ReportBuilder
from xtr_dependency_injection.discovery.bundle_resolver import resolve_bundles
from xtr_dependency_injection.exception import ConfigProviderError
from xtr_dependency_injection.kernel.kernel import assemble, definition_reports
from xtr_dependency_injection.kernel.kernel_bundle import KernelBundle
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import ModuleType

    from xtr_dependency_injection.bundle.bundle import AnyBundle

__all__ = ["injectables"]

_KERNEL_PARAMETERS: Final = "kernel kernel"


def injectables(
    bundles: Sequence[AnyBundle],
    /,
    *,
    configs: Sequence[object] = (),
    env: str = "prod",
    scan: Sequence[str | ModuleType] = (),
) -> list[object]:
    """Return wireup injectables for ``bundles``, their requirements and the core bundle.

    Args:
        bundles: The bundles to integrate. What they require must be listed
            too: nothing is discovered.
        configs: Config values, each the base config of the bundle declaring
            its type.
        env: The environment bundles and ``@when`` conditions see.
        scan: Resources scanned as the application's.

    Raises:
        MissingBundleError: If a required bundle is not listed.
        UnknownConfigTypeError: If a config's type belongs to no listed
            bundle.
        ConfigProviderError: If a bundle or scanned resource produces
            parameters: wireup's ``config=`` is the caller's, so parameters
            need the kernel.
    """
    core = KernelBundle()
    core.info.identify(name="standalone", environment=env, debug=False, project_dir=Path.cwd())
    report = ReportBuilder()
    resolved = resolve_bundles(
        core=core, discovered=(), explicit=bundles, exclude=(), bundle_envs=None, env=env
    )
    core.info.activate([type(bundle).metadata().name for bundle in resolved.bundles])
    report.bundles.extend(resolved.reports)
    assembly = assemble(
        core=core,
        bundles=resolved.bundles,
        discovered=(),
        resources=scan,
        environment=env,
        debug=False,
        exclude=DEFAULT_EXCLUDES,
        report=report,
        given=configs,
    )
    state = assembly.state
    sources = [source for source, _ in state.parameters if source != _KERNEL_PARAMETERS]
    sources.extend(scanned.name for scanned in assembly.parameter_providers)
    if sources:
        raise ConfigProviderError(
            ", ".join(sources),
            "parameters need the kernel: injectables() leaves wireup's config= to the caller",
        )
    ordered = emission_order(state.store.definitions(), state.bundles)
    emitted = emit_injectables(ordered, assembly.decorations, core.resetter.track)
    report.definitions.extend(definition_reports(state, ordered, assembly.decorations))
    core.info.attach(report.freeze())
    return emitted
