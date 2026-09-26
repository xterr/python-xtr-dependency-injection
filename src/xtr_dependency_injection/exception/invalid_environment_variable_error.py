"""An environment variable does not convert to the type asked for."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from .dependency_injection_error import DependencyInjectionError

__all__ = ["InvalidEnvironmentVariableError"]


class InvalidEnvironmentVariableError(DependencyInjectionError):
    """A processor or cast refused a variable's value; a cast's own error is ``__cause__``.

    Attributes:
        name: The variable, or the expression being processed.
        cast: The processor prefix (``"int"``, ``"json"``…) or the callable
            that refused it.
        value: The value refused. Kept out of the message, which is logged:
            the variable may hold a secret.
    """

    name: str
    cast: str | Callable[..., object]
    value: str

    def __init__(self, name: str, cast: str | Callable[..., object], value: str) -> None:
        """Record the variable, the conversion, and the value that failed it."""
        self.name = name
        self.cast = cast
        self.value = value
        converter = cast if isinstance(cast, str) else getattr(cast, "__name__", repr(cast))
        super().__init__(f"environment variable {name} is not a valid {converter}")
