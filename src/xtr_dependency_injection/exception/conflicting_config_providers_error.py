"""Two base providers compete for one config."""

from __future__ import annotations

from ._naming import type_name
from .dependency_injection_error import DependencyInjectionError

__all__ = ["ConflictingConfigProvidersError"]


class ConflictingConfigProvidersError(DependencyInjectionError):
    """Two base providers of one group replace the same config; neither may silently win."""

    config_type: type
    providers: tuple[str, ...]

    def __init__(self, config_type: type, providers: tuple[str, ...]) -> None:
        """Record the config type and the competing providers."""
        self.config_type = config_type
        self.providers = providers
        super().__init__(
            f"{type_name(config_type)} has more than one base provider: {', '.join(providers)}"
        )
