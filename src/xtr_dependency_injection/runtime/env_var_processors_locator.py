"""Every environment variable processor by prefix, and the chain that runs them."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from xtr_dependency_injection.exception import EnvPlaceholderError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .env_var_processor_interface import EnvVarProcessorInterface

__all__ = ["EnvVarProcessorsLocator"]


@final
class EnvVarProcessorsLocator:
    """Resolves an expression such as ``"json:file:SECRETS"`` through its processors.

    Built once per container from every ``container.env_var_processor``
    service; the kernel's ``EnvVarProcessor`` provides the built-in prefixes.
    """

    __slots__ = ("_processors",)

    def __init__(self, processors: Mapping[str, EnvVarProcessorInterface]) -> None:
        """Consult ``processors[prefix]`` for each prefix of an expression."""
        self._processors = dict(processors)

    def get_env(self, name: str) -> object:
        """Return the value of the expression ``name``; no prefix means ``string``.

        Raises:
            EnvPlaceholderError: If a prefix names no processor.
            MissingEnvironmentVariableError: If a variable is not set.
            InvalidEnvironmentVariableError: If a processor refuses a value.
        """
        prefix, separator, local = name.partition(":")
        if not separator:
            prefix, local = "string", name
        processor = self._processors.get(prefix)
        if processor is None:
            raise EnvPlaceholderError(name, f"unsupported env var prefix {prefix!r}")
        return processor.get_env(prefix, local, self.get_env)

    def prefixes(self) -> tuple[str, ...]:
        """Return every prefix a processor provides."""
        return tuple(self._processors)
