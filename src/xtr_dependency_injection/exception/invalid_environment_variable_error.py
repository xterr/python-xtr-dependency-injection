"""An environment variable does not convert to the type asked for."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from .dependency_injection_error import DependencyInjectionError

__all__ = ["InvalidEnvironmentVariableError"]


class InvalidEnvironmentVariableError(DependencyInjectionError):
    """``env()`` could not convert a variable's value; the cast's error is ``__cause__``."""

    name: str
    cast: Callable[[str], object]
    value: str

    def __init__(self, name: str, cast: Callable[[str], object], value: str) -> None:
        """Record the variable, the conversion, and the value that failed it."""
        self.name = name
        self.cast = cast
        self.value = value
        converter = getattr(cast, "__name__", repr(cast))
        super().__init__(f"environment variable {name}={value!r} is not a valid {converter}")
