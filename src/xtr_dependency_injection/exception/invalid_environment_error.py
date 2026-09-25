"""The kernel was asked to run in an environment it does not allow."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["InvalidEnvironmentError"]


class InvalidEnvironmentError(DependencyInjectionError):
    """The environment is not one of the kernel's ``allowed_envs``."""

    env: str
    allowed: tuple[str, ...]

    def __init__(self, env: str, allowed: tuple[str, ...]) -> None:
        """Record the environment asked for and those allowed."""
        self.env = env
        self.allowed = allowed
        super().__init__(f"environment {env!r} is not allowed; allowed: {', '.join(allowed)}")
