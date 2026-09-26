"""A ``@configure`` function, read into what the resolver needs."""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, cast

from xtr_dependency_injection.bundle import NoConfig
from xtr_dependency_injection.decorator.when import when_envs_of, when_not_envs_of
from xtr_dependency_injection.exception import ConfigProviderError
from xtr_dependency_injection.exception._naming import ANNOTATION_HINT, qualified_name

from .configure import configure_of

__all__ = ["ConfigProvider", "config_provider_of"]

_POSITIONAL: Final = frozenset(
    {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
)


@dataclass(frozen=True, slots=True)
class ConfigProvider:
    """One ``@configure`` function, its form and the config type it targets.

    Attributes:
        fn: The decorated function.
        name: ``module:qualname``, as reports and errors show it.
        config_type: The config type it returns.
        form: ``"base"`` replaces the current value; ``"transform"``
            receives it.
        priority: Order among transforms, highest first.
        conditional: Whether ``@when`` or ``@when_not`` restricts it; the
            conditional group applies after, and wins over, the
            unconditional one.
    """

    fn: Callable[..., object]
    name: str
    config_type: type
    form: Literal["base", "transform"]
    priority: int
    conditional: bool

    def apply(self, current: object) -> object:
        """Return what this provider makes of ``current``.

        Raises:
            ConfigProviderError: If it does not return an instance of its
                config type.
            Exception: Whatever it, or the config type's validation, raised
                — with a note naming the provider.
        """
        try:
            produced = self.fn() if self.form == "base" else self.fn(current)
        except Exception as error:
            error.add_note(f"raised by config provider {self.name}")
            raise
        if not isinstance(produced, self.config_type):
            raise ConfigProviderError(
                self.name,
                f"returned {type(produced).__qualname__}, not {self.config_type.__qualname__}",
            )
        return produced


def config_provider_of(fn: Callable[..., object]) -> ConfigProvider:
    """Read a ``@configure`` function into a :class:`ConfigProvider`.

    Raises:
        ConfigProviderError: If ``fn`` is not marked, takes anything but
            nothing (base) or one positional config (transform), has no
            return type, takes a type other than it returns, or targets
            ``NoConfig``.
        NameError: If an annotation cannot be evaluated; the note names the
            provider.
    """
    name = qualified_name(fn)
    marker = configure_of(fn)
    if marker is None:
        raise ConfigProviderError(name, "it is not decorated with @configure")
    hints = _hints(fn, name)
    returned = hints.get("return")
    if not isinstance(returned, type):
        raise ConfigProviderError(name, "its return annotation must be a config type")
    if returned is NoConfig:
        raise ConfigProviderError(name, "NoConfig is never configurable")
    form = _form(fn, name, hints, returned)
    return ConfigProvider(
        fn=fn,
        name=name,
        config_type=returned,
        form=form,
        priority=marker.priority,
        conditional=when_envs_of(fn) is not None or when_not_envs_of(fn) is not None,
    )


def _hints(fn: Callable[..., object], name: str) -> dict[str, object]:
    try:
        return cast("dict[str, object]", typing.get_type_hints(fn, include_extras=True))
    except NameError as error:
        error.add_note(f"while reading config provider {name}: {ANNOTATION_HINT}")
        raise


def _form(
    fn: Callable[..., object], name: str, hints: dict[str, object], returned: type
) -> Literal["base", "transform"]:
    parameters = list(inspect.signature(fn).parameters.values())
    if not parameters:
        return "base"
    if len(parameters) > 1 or parameters[0].kind not in _POSITIONAL:
        raise ConfigProviderError(
            name, "it takes nothing (base form) or one positional config (transform form)"
        )
    if hints.get(parameters[0].name) is not returned:
        raise ConfigProviderError(
            name, f"a transform must take the type it returns, {returned.__qualname__}"
        )
    return "transform"
