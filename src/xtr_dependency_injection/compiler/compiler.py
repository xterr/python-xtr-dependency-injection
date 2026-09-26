"""Running the compiler passes over one build, and keeping what they logged."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from xtr_dependency_injection.builder._origins import origin_of
from xtr_dependency_injection.bundle import KERNEL_BUNDLE
from xtr_dependency_injection.exception._naming import qualified_name

from .pass_config import PassConfig
from .pass_stage import PassStage

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.definition import Origin
    from xtr_dependency_injection.builder.service_configurator import BuildState

    from .compiler_pass_interface import CompilerPassInterface

__all__ = ["Compiler"]


@final
class Compiler:
    """Owns the pass config of one build, runs it, and collects the passes' log.

    Every pass runs with a builder bound to whoever registered it, so what it
    defines carries that origin; the built-in passes run as the kernel.
    """

    __slots__ = ("_log", "_origins", "_pass_config")

    def __init__(self) -> None:
        """Start with the default pass config and an empty log."""
        self._pass_config = PassConfig()
        self._origins: dict[int, Origin] = {}
        self._log: list[str] = []

    def get_pass_config(self) -> PassConfig:
        """Return the pass config."""
        return self._pass_config

    def add_pass(
        self,
        compiler_pass: CompilerPassInterface,
        stage: PassStage = PassStage.BEFORE_OPTIMIZATION,
        priority: int = 0,
        *,
        origin: Origin | None = None,
    ) -> None:
        """Add ``compiler_pass`` to the pass config, run as ``origin`` — the kernel by default.

        Raises:
            TypeError: If ``compiler_pass`` does not implement
                :class:`CompilerPassInterface`.
        """
        self._pass_config.add_pass(compiler_pass, stage, priority)
        if origin is not None:
            self._origins[id(compiler_pass)] = origin

    def log(self, compiler_pass: CompilerPassInterface, message: str) -> None:
        """Record ``message`` under ``compiler_pass``; every line is prefixed with the pass."""
        prefix = f"{qualified_name(type(compiler_pass))}: "
        self._log.append(prefix + message.strip().replace("\n", f"\n{prefix}"))

    def get_log(self) -> list[str]:
        """Return every message the passes logged, in order."""
        return list(self._log)

    def compile(self, state: BuildState) -> None:
        """Run every pass over ``state``, then freeze it.

        The merge pass manages its own phases; every other pass runs in phase
        ``process``.
        """
        # Imported here: the build state imports this module to own a compiler.
        from xtr_dependency_injection.builder.container_builder import (  # noqa: PLC0415
            ContainerBuilder,
        )

        kernel = origin_of(KERNEL_BUNDLE)
        state.phase = "process"
        for compiler_pass in self._pass_config.get_passes():
            origin = self._origins.get(id(compiler_pass), kernel)
            compiler_pass.process(ContainerBuilder(state, origin))
        state.phase = "frozen"
