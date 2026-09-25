"""A ``@configure`` or ``@parameters`` provider cannot be used."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["ConfigProviderError"]


class ConfigProviderError(DependencyInjectionError):
    """A configuration or parameters provider cannot be used.

    Its signature or return is wrong, it was found too late (by a scan a
    bundle requested while loading), it targets ``NoConfig``, it produced a
    bad parameter key, or it carries two markers that exclude each other.
    """

    provider: str
    reason: str

    def __init__(self, provider: str, reason: str) -> None:
        """Record the provider and what is wrong with it."""
        self.provider = provider
        self.reason = reason
        super().__init__(f"invalid provider {provider}: {reason}")
