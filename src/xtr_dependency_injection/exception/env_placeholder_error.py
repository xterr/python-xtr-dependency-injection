"""An environment placeholder used where only its resolved value would do."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["EnvPlaceholderError"]


class EnvPlaceholderError(DependencyInjectionError):
    """An ``env(...)`` placeholder was used as if it were already a value.

    A placeholder stands for a variable read when the service needing it is
    built. Deciding the container's structure with one — testing it in an
    ``if``, embedding a non-scalar in a string, naming an unknown processor
    prefix — cannot work, because the value does not exist yet.

    Attributes:
        expression: The placeholder's expression, e.g. ``"int:PORT"``.
        reason: Why it cannot be used there.
    """

    expression: str
    reason: str

    def __init__(self, expression: str, reason: str) -> None:
        """Record the expression and why it cannot be used there."""
        self.expression = expression
        self.reason = reason
        super().__init__(f"env({expression}): {reason}")
