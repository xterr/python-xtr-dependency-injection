"""Validating each definition on its own, from what the definition itself says.

Definitions a bundle registers through ``ServiceConfigurator`` are consistent
by construction; one hand-built for ``set_definition``, or mutated by a pass,
is not. Later passes and the emitter rely on what this pass checks:

- a ``class`` definition's provider is a class, building its key's type;
- a ``factory`` definition's provider is a plain function with a return
  annotation;
- an ``instance`` definition's provider is an instance of its key's type, and
  a singleton, and takes no arguments;
- every argument names a parameter the provider takes by keyword;
- a factory does not reach an environment placeholder through another
  function or an object it closes over: its own closure and defaults are
  resolved when it is called, what lies behind them is not;
- the lifetime is one the engine knows.
"""

from __future__ import annotations

import inspect
import types
from typing import TYPE_CHECKING, Final, cast, final, get_args

from xtr_dependency_injection.builder.definition import Lifetime
from xtr_dependency_injection.config.env_placeholder import env_placeholders_in
from xtr_dependency_injection.exception import InvalidDefinitionError
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.exception._signatures import evaluated_signature

from ._wireup_bridge import built_type

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.definition import Definition

__all__ = ["CheckDefinitionValidityPass", "invalid_arguments"]

_LIFETIMES: Final = frozenset(get_args(Lifetime))
_BY_KEYWORD: Final = frozenset(
    {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
)


@final
class CheckDefinitionValidityPass:
    """Fails the build on the first definition inconsistent with itself."""

    __slots__ = ()

    def process(self, builder: ContainerBuilder) -> None:
        """Check the kind, provider and lifetime of every definition.

        Raises:
            InvalidDefinitionError: If a definition's provider does not match
                its kind or key, or its lifetime is unknown.
        """
        for definition in builder.get_definitions():
            reason = _invalid(definition)
            if reason is not None:
                raise InvalidDefinitionError(definition.key, reason)


def _invalid(definition: Definition) -> str | None:
    """Return why ``definition`` is invalid, or ``None``."""
    if definition.lifetime not in _LIFETIMES:
        return f"unknown lifetime {definition.lifetime!r}"
    if definition.kind == "class":
        return _invalid_class(definition.provider, definition.key[0]) or invalid_arguments(
            cast("type", definition.provider), definition.arguments
        )
    if definition.kind == "factory":
        return (
            _invalid_factory(definition)
            or invalid_arguments(
                cast("Callable[..., object]", definition.provider), definition.arguments
            )
            or _hidden_placeholder(cast("types.FunctionType", definition.provider))
        )
    return _invalid_instance(definition)


def _invalid_instance(definition: Definition) -> str | None:
    if definition.arguments:
        return "an instance is already built: it takes no arguments"
    if definition.lifetime != "singleton":
        return f"an instance is always a singleton, not {definition.lifetime!r}"
    if not _builds(type(definition.provider), definition.key[0]):
        return f"{definition.provider!r} is not a {qualified_name(definition.key[0])}"
    return None


def _invalid_class(provider: object, provided: type) -> str | None:
    if not isinstance(provider, type):
        return f"a class definition needs a class, not {provider!r}"
    if not _builds(provider, provided):
        return f"class {qualified_name(provider)} is not a {qualified_name(provided)}"
    return None


def _invalid_factory(definition: Definition) -> str | None:
    provider = definition.provider
    if not inspect.isfunction(provider):
        return f"a factory definition needs a function, not {provider!r}"
    if built_type(definition) is None:
        return f"factory {qualified_name(provider)} has no return annotation"
    return None


def invalid_arguments(
    provider: type | Callable[..., object],
    arguments: Mapping[str, object],
    /,
    *,
    reserved: str | None = None,
) -> str | None:
    """Return why ``arguments`` cannot be given to ``provider``, or ``None``.

    An argument is passed by keyword, so it must name a parameter ``provider``
    takes by keyword — or ``provider`` must take ``**kwargs``. ``reserved``
    names a parameter the container fills itself: a decorator's inner service.
    """
    if not arguments:
        return None
    parameters = evaluated_signature(provider).parameters
    open_ended = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    for name in arguments:
        parameter = parameters.get(name)
        if name == reserved:
            return f"argument {name!r} is the decorated service, which the container passes"
        if parameter is None:
            if open_ended:
                continue
            return f"argument {name!r} names no parameter of {qualified_name(provider)}"
        if parameter.kind not in _BY_KEYWORD:
            return f"argument {name!r} names a parameter that cannot be passed by keyword"
    return None


def _hidden_placeholder(factory: types.FunctionType) -> str | None:
    """Return how ``factory`` reaches a placeholder it would receive unresolved, or ``None``."""
    for name, value in _captured(factory):
        if isinstance(value, types.FunctionType):
            if _reaches_placeholder(value, set()):
                return _hidden(name, f"the function {qualified_name(value)}")
        elif _holds_unreachable_placeholder(value):
            return _hidden(name, f"the {type(value).__qualname__} object")
    return None


def _holds_unreachable_placeholder(value: object) -> bool:
    """Tell whether ``value`` holds a placeholder in an attribute resolution cannot rebuild.

    A mapping, sequence, dataclass or model is rebuilt with its placeholders
    resolved; any other object — a bundle, say — is passed as it is.
    """
    if isinstance(value, (type, types.ModuleType)) or env_placeholders_in(value):
        return False
    return bool(env_placeholders_in(dict(getattr(value, "__dict__", {}))))


def _hidden(name: str, holder: str) -> str:
    return (
        f"it reaches an environment placeholder through {name!r}, {holder} it closes over, "
        "which would pass it unresolved: give the value with set_argument(), or inject "
        "the config"
    )


def _reaches_placeholder(function: types.FunctionType, seen: set[int]) -> bool:
    if id(function) in seen:
        return False
    seen.add(id(function))
    values = [value for _, value in _captured(function)]
    if env_placeholders_in((values, function.__defaults__, function.__kwdefaults__)):
        return True
    return any(
        _reaches_placeholder(value, seen)
        for value in values
        if isinstance(value, types.FunctionType)
    )


def _captured(function: types.FunctionType) -> list[tuple[str, object]]:
    """Return ``(name, value)`` for every variable ``function`` closes over and is assigned."""
    captured: list[tuple[str, object]] = []
    for name, cell in zip(function.__code__.co_freevars, function.__closure__ or (), strict=True):
        try:
            captured.append((name, cast("object", cell.cell_contents)))
        except ValueError:  # Never assigned in the enclosing scope.
            continue
    return captured


def _builds(implementation: type, provided: type) -> bool:
    """Return whether ``implementation`` is a ``provided``, when that can be told at runtime.

    A generic alias, or a protocol that cannot be checked at runtime, is given
    the benefit of the doubt: the engine keys by it as written.
    """
    try:
        return issubclass(implementation, provided)
    except TypeError:
        return True
