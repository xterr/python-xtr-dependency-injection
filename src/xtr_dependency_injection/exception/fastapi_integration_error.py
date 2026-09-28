"""A route needed the container, but no kernel serves the application."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["FastapiIntegrationError"]


class FastapiIntegrationError(DependencyInjectionError):
    """The web integration cannot serve a request from the container.

    Raised when a resolver runs with no attached kernel or no open request
    scope, and when a second kernel is attached to an application one
    already serves.

    Attributes:
        reason: What the integration is missing.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record what the integration is missing."""
        self.reason = reason
        super().__init__(reason)
