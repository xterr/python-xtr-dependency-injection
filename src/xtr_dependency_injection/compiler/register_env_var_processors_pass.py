"""Registering the environment variable processors and loaders the container resolves with.

Every service tagged ``container.env_var_processor`` provides the prefixes
its ``get_provided_types`` names, after the kernel's built-in
:class:`EnvVarProcessor` — so a registered processor may replace a built-in
prefix. Every service tagged ``container.env_var_loader`` is asked, in
order, for a variable the environment lacks. The pass defines the built-in
processor (resettable with ``kernel.reset``) and the
:class:`EnvVarProcessorsLocator` the container reads placeholders through,
and records each prefix's types on the parameter bag for
``ValidateEnvPlaceholdersPass``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast, final

# The container evaluates the factories' annotations below at runtime.
from xtr_service_contracts import ContainerInterface  # noqa: TC002 — see above.

from xtr_dependency_injection.builder.definition import Definition, Origin
from xtr_dependency_injection.exception import InvalidDefinitionError
from xtr_dependency_injection.runtime.env_var_processor import EnvVarProcessor
from xtr_dependency_injection.runtime.env_var_processor_interface import (
    EnvVarProcessorInterface,
)
from xtr_dependency_injection.runtime.env_var_processors_locator import EnvVarProcessorsLocator

from ._state import state_of
from ._wireup_bridge import built_type
from .resettable_service_pass import RESET_TAG

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import ServiceKey
    from xtr_dependency_injection.runtime.env_var_loader_interface import EnvVarLoaderInterface

__all__ = ["ENV_VAR_LOADER_TAG", "ENV_VAR_PROCESSOR_TAG", "RegisterEnvVarProcessorsPass"]

ENV_VAR_PROCESSOR_TAG: Final = "container.env_var_processor"
"""The tag autoconfiguration gives every :class:`EnvVarProcessorInterface` service."""

ENV_VAR_LOADER_TAG: Final = "container.env_var_loader"
"""The tag autoconfiguration gives every ``EnvVarLoaderInterface`` service."""

_TYPES: Final = frozenset({"bool", "int", "float", "string", "array", "enum"})


@final
class RegisterEnvVarProcessorsPass:
    """Defines the built-in processor and the locator of every processor by prefix."""

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Collect the tagged processors and loaders and define what resolves with them.

        Raises:
            InvalidDefinitionError: If a tagged processor does not implement
                :class:`EnvVarProcessorInterface`, or names a type other than
                ``bool``, ``int``, ``float``, ``string``, ``array`` or ``enum``.
        """
        state = state_of(builder)
        types = dict(EnvVarProcessor.get_provided_types())
        custom: dict[str, ServiceKey] = {}
        for key in builder.find_tagged_service_ids(ENV_VAR_PROCESSOR_TAG):
            provided = _provided_types(key, built_type(builder.get_definition(*key)))
            for prefix, declared in provided.items():
                custom[prefix] = key
                types[prefix] = declared
        loaders = tuple(builder.find_tagged_service_ids(ENV_VAR_LOADER_TAG))
        environ = state.environ
        kernel = Origin("kernel", "kernel")

        async def env_var_processor(container: ContainerInterface) -> EnvVarProcessor:
            built = [cast("EnvVarLoaderInterface", await container.get(*key)) for key in loaders]
            return EnvVarProcessor(environ, built, container.get_parameter)

        async def env_var_processors_locator(
            container: ContainerInterface, default: EnvVarProcessor
        ) -> EnvVarProcessorsLocator:
            processors: dict[str, EnvVarProcessorInterface] = dict.fromkeys(
                EnvVarProcessor.get_provided_types(), default
            )
            for prefix, key in custom.items():
                processors[prefix] = cast("EnvVarProcessorInterface", await container.get(*key))
            return EnvVarProcessorsLocator(processors)

        _ = builder.set_definition(
            Definition(
                (EnvVarProcessor, None), env_var_processor, "factory", "singleton", kernel
            ).add_tag(RESET_TAG, method="reset")
        )
        _ = builder.set_definition(
            Definition(
                (EnvVarProcessorsLocator, None),
                env_var_processors_locator,
                "factory",
                "singleton",
                kernel,
            )
        )
        state.parameter_bag.set_provided_types(types)


def _provided_types(key: ServiceKey, built: type | None) -> Mapping[str, str]:
    if not (isinstance(built, type) and issubclass(built, EnvVarProcessorInterface)):
        reason = f"tagged {ENV_VAR_PROCESSOR_TAG} but does not implement EnvVarProcessorInterface"
        raise InvalidDefinitionError(key, reason)
    provided = built.get_provided_types()
    for prefix, declared in provided.items():
        unknown = set(declared.split("|")) - _TYPES
        if unknown:
            reason = f"prefix {prefix!r} provides {min(unknown)!r}; the types are " + ", ".join(
                sorted(_TYPES)
            )
            raise InvalidDefinitionError(key, reason)
    return provided
