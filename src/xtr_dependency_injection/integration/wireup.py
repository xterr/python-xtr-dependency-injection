"""The one place this package exposes its engine.

Use it only for framework integrations (for example
``wireup.integration.fastapi.setup(engine_container(compiled), app)``) or for
plain-wireup applications that want to reuse the bundle pipeline without a
kernel: :func:`injectables` for the services alone, :func:`create_container`
for a container with its parameters too.

Every other public surface stays behind :class:`ContainerInterface`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from xtr_dependency_injection.compiler.wireup_compiler import compile_container
from xtr_dependency_injection.config.env_placeholder import ENV_PARAMETERS_ROOT, env_tokens
from xtr_dependency_injection.config.parameters import merge_parameters
from xtr_dependency_injection.exception import ConfigProviderError
from xtr_dependency_injection.kernel.booted_kernel import BootedKernel
from xtr_dependency_injection.kernel.compiled_kernel import CompiledKernel
from xtr_dependency_injection.kernel.kernel import prepare
from xtr_dependency_injection.scan.default_excludes import DEFAULT_EXCLUDES

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import ModuleType

    from wireup import AsyncContainer

    from xtr_dependency_injection.bundle.bundle import AnyBundle

__all__ = ["create_container", "engine_container", "injectables"]

_NEEDS_PARAMETERS = "parameters need create_container() or the kernel, not wireup's config="


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
            need :func:`create_container` or the kernel.
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
    sources = [
        origin.name if origin.kind == "app" else str(origin)
        for origin, _ in state.parameters
        if origin.kind != "kernel"
    ]
    if sources:
        raise ConfigProviderError(
            ", ".join(sources),
            _NEEDS_PARAMETERS,
        )
    _ = prepared.finish_report()
    return prepared.injectables


def create_container(  # noqa: PLR0913 — the pipeline's inputs, plus the caller's parameters.
    bundles: Sequence[type[AnyBundle]],
    /,
    *,
    configs: Sequence[object] = (),
    env: str = "prod",
    scan: Sequence[str | ModuleType] = (),
    parameters: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> AsyncContainer:
    """Return a wireup container for ``bundles``, compiled as the kernel compiles one.

    What :func:`injectables` returns, compiled together with the parameters
    — the kernel's, the bundles', ``@parameters``' and those
    ``Autowire(env=...)`` reads — so parameter and environment variable
    injections work without a kernel. Boot and shutdown hooks do not run.

    Args:
        bundles: As for :func:`injectables`.
        configs: As for :func:`injectables`.
        env: As for :func:`injectables`.
        scan: As for :func:`injectables`.
        parameters: The caller's own parameters, merged with the others.
        environ: Where environment variables are read, instead of the
            process environment.

    Raises:
        ParameterConflictError: If ``parameters`` sets a parameter another
            source sets.
        ContainerCompilationError: If the engine refuses the container.
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
        environ=environ,
    )
    sources = [
        (origin.name if origin.kind == "app" else str(origin), values)
        for origin, values in prepared.assembly.state.parameters
    ]
    if parameters is not None:
        sources.append(("create_container(parameters=...)", parameters))
    merged = merge_parameters(sources)
    merged[ENV_PARAMETERS_ROOT] = env_tokens()
    container = compile_container(
        prepared.injectables, prepared.ordered, parameters=merged, concurrent_scoped_access=False
    )
    _ = prepared.finish_report()
    return container


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
