"""Reading an annotation through the ``type`` aliases it is written with.

``type Mailers = Sequence[Mailer]`` makes ``Mailers`` a :class:`typing.TypeAliasType`:
an object standing for ``Sequence[Mailer]`` that hides it until its ``__value__`` is read.
The container keys services by type and reads its markers off ``Annotated``, and the engine
underneath knows nothing of aliases, so an alias left in an annotation names a service no one
registered, or hides the marker that says a parameter is the container's to fill. Every
annotation the container reads goes through :func:`without_type_aliases` first, so an alias
means exactly what it stands for, wherever it is written. It lives in the leaf layer, beside
:mod:`._signatures`, so every layer reads annotations the same way.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Annotated,
    Literal,
    Protocol,
    TypeAliasType,
    TypeVar,
    cast,
    get_args,
    get_origin,
)

if TYPE_CHECKING:
    import inspect
    from collections.abc import Sequence

__all__ = ["signature_without_type_aliases", "without_type_aliases"]


class _Subscriptable(Protocol):
    """A typing form applied to arguments with ``[]``: ``Annotated``, ``list``, ``dict[K, V]``."""

    def __getitem__(self, arguments: object, /) -> object: ...


def without_type_aliases(annotation: object) -> object:
    """Return ``annotation`` with every ``type`` alias in it replaced by what it stands for.

    An alias is expanded wherever it sits: alone, applied to arguments (``Pair[int]``),
    inside ``Annotated`` — its metadata kept —, as a member of a union, or as an argument of a
    generic (``Sequence[Alias]``). ``Literal`` values are values, never read as types.

    An annotation holding no alias is returned as it is, the same object, so a reader comparing
    by identity sees no change. A recursive alias (``type Json = dict[str, Json] | str``) is
    expanded once along each path and then left as it is, so reading one ends. A form that
    cannot be rebuilt around its expanded arguments is left as it was written.
    """
    return _expanded(annotation, frozenset())


def signature_without_type_aliases(signature: inspect.Signature) -> inspect.Signature:
    """Return ``signature`` with :func:`without_type_aliases` applied to every annotation.

    The parameters' and the return's. ``signature`` itself comes back when none held an alias.
    """
    parameters = list(signature.parameters.values())
    changed = False
    for index, parameter in enumerate(parameters):
        annotation = cast("object", parameter.annotation)
        expanded = without_type_aliases(annotation)
        if expanded is not annotation:
            parameters[index] = parameter.replace(annotation=expanded)
            changed = True
    returned = cast("object", signature.return_annotation)
    expanded_return = without_type_aliases(returned)
    if not changed and expanded_return is returned:
        return signature
    return signature.replace(parameters=parameters, return_annotation=expanded_return)


def _expanded(annotation: object, expanding: frozenset[TypeAliasType]) -> object:
    """Expand ``annotation``; ``expanding`` holds the aliases already opened on this path."""
    if isinstance(annotation, TypeAliasType):
        return _opened(annotation, annotation, (), expanding)
    if isinstance(annotation, list):
        # The parameter list of ``Callable[[A, B], R]``.
        items = cast("list[object]", annotation)
        expanded_items = [_expanded(item, expanding) for item in items]
        return items if _same(expanded_items, items) else expanded_items
    origin = cast("object", get_origin(annotation))
    arguments = cast("tuple[object, ...]", get_args(annotation))
    if isinstance(origin, TypeAliasType):
        return _opened(annotation, origin, arguments, expanding)
    if origin is None or origin is Literal or not arguments:
        return annotation
    return _expanded_arguments(annotation, origin, arguments, expanding)


def _expanded_arguments(
    annotation: object,
    origin: object,
    arguments: tuple[object, ...],
    expanding: frozenset[TypeAliasType],
) -> object:
    """Expand what ``annotation`` applies ``origin`` to; ``Annotated`` keeps its metadata."""
    if origin is Annotated:
        wrapped = _expanded(arguments[0], expanding)
        if wrapped is arguments[0]:
            return annotation
        return _subscripted(Annotated, (wrapped, *arguments[1:]))
    expanded = tuple(_expanded(argument, expanding) for argument in arguments)
    return annotation if _same(expanded, arguments) else _rebuilt(annotation, origin, expanded)


def _opened(
    annotation: object,
    alias: TypeAliasType,
    arguments: tuple[object, ...],
    expanding: frozenset[TypeAliasType],
) -> object:
    """Expand what ``alias``, applied to ``arguments``, stands for — once along this path."""
    if alias in expanding:
        return annotation
    value = _applied(alias, arguments) if arguments else cast("object", alias.__value__)
    if value is None:
        return annotation
    return _expanded(value, expanding | {alias})


def _same(expanded: Sequence[object], written: Sequence[object]) -> bool:
    """Tell whether expanding changed none of ``written``."""
    return all(new is old for new, old in zip(expanded, written, strict=True))


def _applied(alias: TypeAliasType, arguments: tuple[object, ...]) -> object | None:
    """Return what ``alias`` applied to ``arguments`` stands for, or ``None`` if unsure.

    ``type Pair[K, V] = dict[V, K]`` applied to ``(int, str)`` is ``dict[str, int]``: each
    argument replaces its parameter by name, not by where the parameter first appears in the
    value. Only plain type variables are substituted; any other kind of parameter, or a count
    that does not match, leaves the application as written.
    """
    parameters = alias.__type_params__
    if len(parameters) != len(arguments) or not all(isinstance(p, TypeVar) for p in parameters):
        return None
    mapping = dict(zip(parameters, arguments, strict=True))
    value = cast("object", alias.__value__)
    if isinstance(value, TypeVar):
        return mapping.get(value, value)
    free = cast("tuple[object, ...]", getattr(value, "__parameters__", ()))
    if not free:
        return value
    if not all(parameter in mapping for parameter in free):
        return None
    substituted = tuple(mapping[cast("TypeVar", parameter)] for parameter in free)
    # One argument per free variable: the count the value expects, so it takes them.
    return _subscripted(value, substituted)


def _rebuilt(annotation: object, origin: object, arguments: tuple[object, ...]) -> object:
    """Return ``origin`` applied to ``arguments`` — ``annotation`` again if it refuses them.

    A form subscripted through a ``__class_getitem__`` of its own may accept the alias and
    refuse what it stands for; the annotation then reads as written, as it did before.
    """
    try:
        return _subscripted(origin, arguments)
    except TypeError:
        return annotation


def _subscripted(form: object, arguments: tuple[object, ...]) -> object:
    """Return ``form[arguments]``, one argument given alone — as ``form[a]`` writes it.

    ``Annotated`` takes its wrapped type and metadata as one tuple, however many there are.

    Raises:
        TypeError: If ``form`` refuses ``arguments``.
    """
    key = arguments[0] if len(arguments) == 1 and form is not Annotated else arguments
    return cast("_Subscriptable", form)[key]
