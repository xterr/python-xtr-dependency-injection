"""Where environment variables come from when the process environment does not have them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["EnvVarLoaderInterface"]


@runtime_checkable
class EnvVarLoaderInterface(Protocol):
    """Loads variables from somewhere else — a secrets directory, a vault, a remote store.

    A service implementing this interface is autoconfigured with the
    ``container.env_var_loader`` tag. Loaders are asked, in registration
    order, only for a variable the process environment does not set, and
    each one is loaded once until the processor is reset.
    """

    def load_env_vars(self) -> Mapping[str, str]:
        """Return every variable this loader provides, by name."""
        ...
