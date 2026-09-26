"""A parameter embedded in a string that is not a string or a number."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["InvalidParameterTypeError"]


class InvalidParameterTypeError(DependencyInjectionError):
    """A ``%name%`` reference inside a longer string names a value that cannot be embedded.

    Attributes:
        name: The parameter referenced.
        type_name: The type of its value.
        value: The string it was embedded in.
    """

    name: str
    type_name: str
    value: str

    def __init__(self, name: str, type_name: str, value: str) -> None:
        """Record the parameter, its type, and the string it was embedded in."""
        self.name = name
        self.type_name = type_name
        self.value = value
        found = f"parameter {name!r} of type {type_name} inside string value {value!r}"
        super().__init__(f"a string value must be composed of strings and/or numbers: {found}")
