"""A service decorator does not declare its inner service correctly."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["DecoratorSignatureError"]


class DecoratorSignatureError(DependencyInjectionError):
    """A decorator lacks exactly one ``AutowireDecorated`` parameter of the decorated type."""

    decorator: str
    reason: str

    def __init__(self, decorator: str, reason: str) -> None:
        """Record the decorator and what is wrong with its signature."""
        self.decorator = decorator
        self.reason = reason
        super().__init__(f"invalid decorator {decorator}: {reason}")
