"""The one place this package exposes its engine.

Use it only for framework integrations (for example
``wireup.integration.fastapi.setup(engine_container(compiled), app)``) or for
plain-wireup applications that want to reuse the bundle pipeline without a
kernel.

Every other public surface stays behind :class:`ContainerInterface`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from xtr_dependency_injection.exception import ConfigProviderError
from xtr_dependency_injection.kernel.booted_kernel import BootedKernel
from xtr_dependency_injection.kernel.compiled_kernel import CompiledKernel
from xtr_dependency_injection.kernel.kernel import prepare
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import ModuleType

    from wireup import AsyncContainer

    from xtr_dependency_injection.bundle.bundle import AnyBundle

__all__ = ["engine_container", "injectables"]


def injectables(
    bundles: Sequence[type[AnyBundle]],
    /,
    *,
    configs: Sequence[object] = (),
    env: str = "prod",
    scan: Sequence[str | ModuleType] = (),
) -> list[object]:
    """Return wireup injectables for ``bundles``, their requirements and the core bundle.

    Runs the same pipeline the kernel does — requirements, configs, load,
    autoconfigure, process — without scanning an application package, and
    returns what to spread into
    ``create_async_container(injectables=[...])``.

    Bundle classes are listed here (not instances): the pipeline
    instantiates only the active ones, exactly as the kernel does. Every
    listed bundle is activated (``{"all": True}`` semantics); required
    bundles are pulled in recursively. Boot and shutdown hooks do not run.

    Args:
        bundles: The bundle classes to integrate; every listed class is
            activated for ``env`` and its ``@required_bundle`` peers are
            pulled in recursively.
        configs: Config values, each the base config of the bundle declaring
            its type.
        env: The environment bundles and ``@when`` conditions see.
        scan: Resources scanned as the application's.

    Raises:
        MissingBundleError: If a required string target cannot be imported
            and its declaration is not ``ignore_on_invalid``.
        UnknownConfigTypeError: If a config's type belongs to no listed
            bundle.
        ConfigProviderError: If a bundle or scanned resource produces
            parameters: wireup's ``config=`` is the caller's, so parameters
            need the kernel.
    """
    listed = {bundle_type: {"all": True} for bundle_type in bundles}
    prepared = prepare(
        name="standalone",
        environment=env,
        debug=False,
        project_dir=Path.cwd(),
        listed=listed,
        resources=scan,
        exclude=DEFAULT_EXCLUDES,
        given=configs,
    )
    state = prepared.assembly.state
    sources = [str(origin) for origin, _ in state.parameters if origin.kind != "kernel"]
    sources.extend(scanned.name for scanned in prepared.assembly.parameter_providers)
    if sources:
        raise ConfigProviderError(
            ", ".join(sources),
            "parameters need the kernel: injectables() leaves wireup's config= to the caller",
        )
    _ = prepared.finish_report()
    return prepared.injectables


def engine_container(kernel: CompiledKernel | BootedKernel, /) -> AsyncContainer:
    """Return the underlying wireup ``AsyncContainer`` of ``kernel``.

    For framework integrations that need the concrete engine handle, for
    example::

        wireup.integration.fastapi.setup(engine_container(compiled), app)

    Args:
        kernel: A compiled or booted kernel produced by :class:`Kernel`.

    Returns:
        The wireup ``AsyncContainer`` that backs the kernel's
        :class:`ContainerInterface`.
    """
    # A defensive isinstance guard for foreign callers (e.g. plain wireup users
    # that hand us a mock); every legitimate caller has the union type.
    if not isinstance(kernel, (CompiledKernel, BootedKernel)):  # pyright: ignore[reportUnnecessaryIsInstance]
        message = "engine_container needs a CompiledKernel or BootedKernel"  # pyright: ignore[reportUnreachable]
        raise TypeError(message)
    return kernel._engine  # noqa: SLF001 — the integration module owns this contract.  # pyright: ignore[reportPrivateUsage]
