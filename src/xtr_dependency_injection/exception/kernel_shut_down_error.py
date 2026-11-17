"""A service is asked of a kernel that shut down."""

from __future__ import annotations

from .dependency_injection_error import DependencyInjectionError

__all__ = ["KernelShutDownError"]


class KernelShutDownError(DependencyInjectionError):
    """The kernel whose container is asked for a service has shut down.

    Its singletons were closed when it did, so handing one out — or building
    a new one nothing would ever close — is refused.
    """

    def __init__(self) -> None:
        """Compose the message."""
        super().__init__("this kernel has shut down; its container resolves nothing any more")
