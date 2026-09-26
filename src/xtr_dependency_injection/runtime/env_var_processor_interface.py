"""What turns one prefix of an environment variable expression into a value."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = ["EnvVarProcessorInterface"]


@runtime_checkable
class EnvVarProcessorInterface(Protocol):
    """Processes the prefixes it provides, e.g. ``int`` in ``env("int:PORT")``.

    A service implementing this interface is autoconfigured with the
    ``container.env_var_processor`` tag and consulted for every prefix its
    :meth:`get_provided_types` names; the kernel's own ``EnvVarProcessor``
    provides the built-in ones.
    """

    def get_env(self, prefix: str, name: str, get_env: Callable[[str], object]) -> object:
        """Return the value of ``prefix:name``.

        Args:
            prefix: The prefix being processed.
            name: What follows it: a variable name, or a further expression
                (``"file:SECRETS"`` in ``"json:file:SECRETS"``) to resolve with
                ``get_env``.
            get_env: Resolves the rest of the chain.
        """
        ...

    @classmethod
    def get_provided_types(cls) -> Mapping[str, str]:
        """Return each prefix provided, mapped to the types it produces (``"int"``, ``"array"``)."""
        ...
