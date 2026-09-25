"""A ``@configure`` provider targets a config type no active bundle owns."""

from __future__ import annotations

from ._naming import type_name
from .dependency_injection_error import DependencyInjectionError

__all__ = ["UnknownConfigTypeError"]


class UnknownConfigTypeError(DependencyInjectionError):
    """No active bundle owns the config type a provider returns.

    ``inactive_bundle`` names the bundle that owns it but is excluded or
    disabled in this environment — usually the real cause.
    """

    provider: str
    config_type: type
    inactive_bundle: str | None

    def __init__(self, provider: str, config_type: type, inactive_bundle: str | None) -> None:
        """Record the provider, its config type, and the inactive owner, if any."""
        self.provider = provider
        self.config_type = config_type
        self.inactive_bundle = inactive_bundle
        owner = (
            f"its bundle {inactive_bundle!r} is not active"
            if inactive_bundle is not None
            else "no bundle declares it"
        )
        super().__init__(f"{provider} configures {type_name(config_type)}, but {owner}")
