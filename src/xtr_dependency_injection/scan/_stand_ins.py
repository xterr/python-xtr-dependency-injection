"""What a set-aside module is inspected with: stand-ins for the packages that are not installed.

A module the application scan cannot import, because a package it needs is not
installed, has its code run in a namespace of its own to learn what it
defines. To that module's own import statements alone, each such package is
answered by a :class:`StandInModule`, and every name taken from it by a
:class:`StandIn`: an object that can be imported, subclassed, subscripted,
called, compared, counted and read, so module-level code built on the missing
package runs to its end. Nothing it produces is used afterwards: the module is
set aside, then dropped.

Private to the scan.
"""

from __future__ import annotations

import sys
from types import BuiltinFunctionType, FunctionType, ModuleType
from typing import TYPE_CHECKING, Final, cast, final, override

from ._frames import running_module

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "STAND_IN_ATTRIBUTE",
    "StandIn",
    "StandInModule",
    "unwrapped",
]

STAND_IN_ATTRIBUTE: Final = "__xtr_stand_in__"
"""Set on a class standing in as a base, to the dotted name it stands for."""

_DECORATED_TYPES: Final = (
    type,
    FunctionType,
    BuiltinFunctionType,
    staticmethod,
    classmethod,
    property,
)
"""What a decorator is handed: a class, or what a function definition makes."""


@final
class StandIn:
    """Stands for anything taken from a package that is not installed.

    Every attribute, item, call and operation is another stand-in, named
    after the path that reached it. A call handed exactly one class or
    function — or a stand-in remembering one — *remembers* it, since whether it
    is a decorator (``@lib.register``) or a decorator factory
    (``@lib.depends_on(Users)``) cannot be told yet:

    - a remembering stand-in, called in turn with one class or function,
      returns that argument — the factory's decorator gave back what it
      decorated;
    - it reads the remembered object's attributes — a stand-in for one the
      object lacks — and is derived from as that class, only when no module
      loaded truthfully defines it: the inspected module's own, or a
      set-aside one's. Of a class of a module that is loaded, it reads
      nothing and derives from nothing, so no code of that module runs;
    - it sets attributes on the object only when the inspected module
      defines it — a decorator applied over it still marks the class it
      decorates, and nothing of another module is changed;
    - :func:`unwrapped` gives back the object, for the scan to see what a
      module defines.

    Called as a metaclass — a name, a tuple of bases, a namespace — it builds
    the class. As a base it is a plain class of its own, marked with
    :data:`STAND_IN_ATTRIBUTE`.
    """

    __slots__ = ("_base", "_path", "_remembered")

    _path: str
    _base: type | None
    _remembered: object | None

    def __init__(self, path: str, remembered: object | None = None) -> None:
        """Stand for ``path``, the dotted name it was reached by, remembering ``remembered``."""
        self._path = path
        self._base = None
        self._remembered = remembered

    def __getattr__(self, name: str) -> object:
        """Return the remembered object's ``name`` where it may be read, else a stand-in for it.

        A dunder neither has is answered as by any object without it.
        """
        if self._remembered is not None and _readable(self._remembered):
            try:
                return cast("object", getattr(self._remembered, name))
            except AttributeError:
                pass
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return StandIn(f"{self._path}.{name}")

    @override
    def __setattr__(self, name: str, value: object) -> None:
        """Set one of its own slots; else ``name`` on the remembered object of this module.

        Only an object the module running now defines — the one inspected —
        is changed: a factory handed a class of another module leaves it be.
        """
        if name in StandIn.__slots__:
            object.__setattr__(self, name, value)
        elif (
            self._remembered is not None
            and getattr(self._remembered, "__module__", None) == running_module()
        ):
            setattr(self._remembered, name, value)

    def __call__(self, *args: object, **kwargs: object) -> object:
        """Decorate, build a class, or stand for the call's result — see the class."""
        if len(args) == 1 and not kwargs and _is_decorated(args[0]):
            if self._remembered is not None:
                return args[0]
            return StandIn(f"{self._path}()", unwrapped(args[0]))
        # A class statement's keywords go to its metaclass; one standing in takes none of them.
        built = _class_built(args)
        if built is not None:
            return built
        return StandIn(f"{self._path}()")

    def __getitem__(self, key: object) -> StandIn:
        """Return the stand-in for a subscription, such as a generic alias."""
        del key
        return StandIn(f"{self._path}[]")

    def __setitem__(self, key: object, value: object) -> None:
        """Let an item be set."""
        del key, value

    def __delitem__(self, key: object) -> None:
        """Let an item be deleted."""
        del key

    def __iter__(self) -> Iterator[object]:
        """Iterate over nothing."""
        return iter(())

    def __len__(self) -> int:
        """Hold nothing."""
        return 0

    def __contains__(self, item: object) -> bool:
        """Hold nothing."""
        del item
        return False

    def __bool__(self) -> bool:
        """Be something."""
        return True

    def __index__(self) -> int:
        """Be zero where a number is needed."""
        return 0

    def __int__(self) -> int:
        """Be zero where a number is needed."""
        return 0

    def __float__(self) -> float:
        """Be zero where a number is needed."""
        return 0.0

    def __round__(self, ndigits: int | None = None) -> int:
        """Be zero where a number is needed."""
        del ndigits
        return 0

    def __trunc__(self) -> int:
        """Be zero where a number is needed."""
        return 0

    def __floor__(self) -> int:
        """Be zero where a number is needed."""
        return 0

    def __ceil__(self) -> int:
        """Be zero where a number is needed."""
        return 0

    def __enter__(self) -> StandIn:
        """Be its own context."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Leave the context, raising nothing of its own."""
        del exc_info

    def __instancecheck__(self, instance: object) -> bool:
        """Have no instance: nothing is an instance of what is not installed."""
        del instance
        return False

    def __subclasscheck__(self, subclass: object) -> bool:
        """Have no subclass: nothing derives from what is not installed."""
        del subclass
        return False

    def __mro_entries__(self, bases: tuple[object, ...]) -> tuple[type]:
        """Be derived from: as the remembered class where readable, else as a class of its own."""
        del bases
        if isinstance(self._remembered, type) and _readable(self._remembered):
            return (self._remembered,)
        base = self._base
        if base is None:
            module, _, name = self._path.rpartition(".")
            base = type(name or self._path, (_StandInBase,), {"__module__": module})
            setattr(base, STAND_IN_ATTRIBUTE, self._path)
            self._base = base
        return (base,)

    def _operation(self, *other: object) -> StandIn:
        del other
        return StandIn(f"{self._path}()")

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _operation
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = _operation
    __mod__ = __rmod__ = __pow__ = __rpow__ = __matmul__ = __rmatmul__ = _operation
    __and__ = __rand__ = __xor__ = __rxor__ = __lshift__ = __rshift__ = _operation
    __or__ = __ror__ = __neg__ = __pos__ = __abs__ = __invert__ = _operation
    __lt__ = __le__ = __gt__ = __ge__ = _operation

    @override
    def __repr__(self) -> str:
        return f"<stand-in for {self._path}>"


class _StandInBase:
    """What a class derived from a stand-in derives from; what it is subclassed with is let be."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        super().__init_subclass__()


def _is_decorated(obj: object) -> bool:
    """Whether ``obj`` is what a decorator is handed — or a stand-in remembering one."""
    return isinstance(unwrapped(obj), _DECORATED_TYPES)


def _readable(remembered: object) -> bool:
    """Whether a remembering stand-in may read ``remembered``: no truthfully loaded module's."""
    module = getattr(remembered, "__module__", None)
    return module == running_module() or module not in sys.modules


def _class_built(args: tuple[object, ...]) -> type | None:
    """Build the class a stand-in metaclass is called for — a name, bases, a namespace."""
    if len(args) != 3:  # noqa: PLR2004 — the three arguments a metaclass is called with
        return None
    name, bases, namespace = args
    if not (isinstance(name, str) and isinstance(bases, tuple) and isinstance(namespace, dict)):
        return None
    # What a class statement hands its metaclass: a tuple of bases, a namespace of names.
    classes = tuple(base for base in cast("tuple[object, ...]", bases) if isinstance(base, type))
    return type(name, classes, dict(cast("dict[str, object]", namespace)))


def unwrapped(obj: object) -> object:
    """Return what a remembering stand-in remembers, and anything else as it is."""
    if isinstance(obj, StandIn):
        remembered = cast("object | None", object.__getattribute__(obj, "_remembered"))
        return remembered if remembered is not None else obj
    return obj


@final
class StandInModule(ModuleType):
    """A module of a package that is not installed: every name taken from it is a stand-in."""

    @override
    def __getattr__(self, name: str) -> StandIn:
        """Return the stand-in for ``name``; a dunder is answered as by any module without it."""
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return StandIn(f"{self.__name__}.{name}")
