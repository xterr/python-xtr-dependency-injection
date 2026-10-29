"""What a bundle list holds in place of a bundle class whose package is not installed.

An application imports every bundle it lists at the top of its bundle list,
while a deployment installs only the runtime dependencies. The kernel reads
such a list with each missing package stood in for, and every name imported
from one becomes an :class:`AbsentBundle`: enough to key ``BUNDLES`` and to be
reported, and nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, final

__all__ = ["AbsentBundle"]


@final
@dataclass(frozen=True, slots=True)
class AbsentBundle:
    """Stands for a class imported from a module that is not installed.

    Two stand-ins for one class are equal, so either keys the same entry. Any
    other use raises the :class:`ModuleNotFoundError` the import itself would
    have: code that needs the class, rather than its place in ``BUNDLES``,
    still fails, and names the module it needs.

    Attributes:
        module: The module the class was imported from.
        name: The name it was imported by.
    """

    module: str
    name: str

    @property
    def target(self) -> str:
        """``"module:Name"``, the way a bundle is named without importing it."""
        return f"{self.module}:{self.name}"

    def __getattr__(self, attribute: str) -> NoReturn:
        """Refuse every attribute: there is no class here to have one.

        A dunder is answered as by any object without it — what asks for one
        is a protocol probing for an optional hook, such as ``copy`` looking
        for ``__deepcopy__`` — so only a use of the class itself raises.
        """
        if attribute.startswith("__") and attribute.endswith("__"):
            raise AttributeError(attribute)
        raise self._missing()

    def __call__(self, *args: object, **kwargs: object) -> NoReturn:
        """Refuse to build: there is no class here to instantiate."""
        del args, kwargs
        raise self._missing()

    def __mro_entries__(self, bases: tuple[object, ...]) -> NoReturn:
        """Refuse to be subclassed: there is no class here to derive from."""
        del bases
        raise self._missing()

    def _missing(self) -> ModuleNotFoundError:
        message = (
            f"No module named {self.module!r}: {self.name} was taken from it only to key "
            "the application's BUNDLES"
        )
        return ModuleNotFoundError(message, name=self.module)
