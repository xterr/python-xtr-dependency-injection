"""Turning definitions into what wireup registers, without marking the caller's objects.

``@injectable`` works by writing an attribute onto what it decorates. Applied
to a library's class or function, that attribute would leak into every other
container the object is ever scanned by. So nothing here decorates what it is
given: a function is cloned, a class gets a factory synthesized for it, and
only the clone or the factory is marked.

A synthesized factory calls the class itself, so ``container.get(cls)``
returns an instance of the real class — not of a private subclass created to
carry the mark, as the per-library integrations used to do.
"""

from __future__ import annotations

import inspect
import types
from collections.abc import AsyncGenerator, AsyncIterator, Generator, Iterator
from typing import TYPE_CHECKING, Annotated, Any, Final, cast

from xtr_dependency_injection.exception._signatures import evaluated_signature

from ._wireup_bridge import REGISTRATION_ATTRIBUTE, to_engine_signature

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "_alias_factory",
    "_box_type",
    "_clone_function",
    "_decorating_factory",
    "_map_result",
    "_null_decorator_factory",
    "_synthesize_class_factory",
]

_BOX_MODULE: Final = "xtr_dependency_injection.compiler"
_INNER_BOX_PARAMETER: Final = "_xtr_inner_box"


def _clone_function(fn: Callable[..., object]) -> types.FunctionType:
    """Return a copy of ``fn`` that can be marked without marking ``fn``.

    Built from the same code object, so a coroutine, generator or async
    generator function stays one: wireup decides whether to await a factory
    and whether it cleans up by the kind of function it is given.
    """
    original = cast("types.FunctionType", fn)
    clone = types.FunctionType(
        original.__code__,
        original.__globals__,
        original.__name__,
        original.__defaults__,
        original.__closure__,
    )
    clone.__kwdefaults__ = original.__kwdefaults__
    clone.__annotations__ = dict(original.__annotations__)
    clone.__qualname__ = original.__qualname__
    clone.__module__ = original.__module__
    clone.__dict__.update(
        {key: value for key, value in original.__dict__.items() if key != REGISTRATION_ATTRIBUTE}
    )
    type_params = cast("tuple[object, ...] | None", getattr(original, "__type_params__", None))
    if type_params:
        # PEP 695 (3.12+); absent from the 3.11 stubs this package is checked against.
        _set(clone, __type_params__=type_params)
    # Rewrite our Autowire/Target markers to wireup's before the engine reads the clone.
    _set(clone, __signature__=to_engine_signature(_evaluated_signature(clone)))
    return clone


def _evaluated_signature(target: Callable[..., object] | type) -> inspect.Signature:
    """Return ``target``'s signature with every annotation evaluated.

    A wrapper presenting this signature lives in another module than
    ``target``, so a string annotation could no longer be resolved against the
    right globals: evaluate them now, against ``target``'s own — including a
    string nested inside ``Annotated[...]`` (see :func:`evaluated_signature`).

    Raises:
        NameError: If an annotation names something not importable at
            runtime; the note names ``target``.
    """
    return evaluated_signature(target)


def _synthesize_class_factory(cls: type) -> Callable[..., object]:
    """Return a factory building ``cls``, registered under ``cls`` itself.

    It presents the constructor's signature, so wireup injects exactly what
    ``cls`` asks for, and is named like ``cls``, so wireup's messages read as
    if they were about it.
    """

    def build(**kwargs: object) -> object:
        return cls(**kwargs)

    _set(
        build,
        __signature__=to_engine_signature(_evaluated_signature(cls)).replace(return_annotation=cls),
        __annotations__={"return": cls},
        __module__=cls.__module__,
        __qualname__=cls.__qualname__,
        __name__=cls.__name__,
    )
    return build


def _alias_factory(
    alias_type: type,
    target_type: type,
    target_qualifier: object | None,
) -> Callable[..., object]:
    """Return a factory forwarding ``(target_type, target_qualifier)`` under ``alias_type``.

    The alias shares the target's instance. The synthesized factory takes
    the target as an injected parameter and hands it back, so wireup
    resolves the alias through the target definition without duplicating
    state.
    """
    import wireup  # noqa: PLC0415 — only compiler code may reach wireup.

    annotated: Any = Annotated
    annotation = cast("type", annotated[target_type, wireup.Inject(qualifier=target_qualifier)])
    parameter = inspect.Parameter("target", inspect.Parameter.KEYWORD_ONLY, annotation=annotation)
    signature = inspect.Signature(parameters=[parameter], return_annotation=alias_type)

    def forward(**kwargs: object) -> object:
        return kwargs["target"]

    _set(
        forward,
        __signature__=signature,
        __annotations__={"target": annotation, "return": alias_type},
        __module__=_BOX_MODULE,
        __qualname__=f"_alias_forward_{alias_type.__name__}",
        __name__=f"_alias_forward_{alias_type.__name__}",
    )
    return forward


def _map_result(
    factory: Callable[..., object],
    fn: Callable[[Any], object],
    /,
    *,
    provides: object,
) -> Callable[..., object]:
    """Return a factory of ``factory``'s kind producing ``fn(value)`` for each value built.

    Sync stays sync, a coroutine function stays one, and a generator or async
    generator factory stays a generator: wireup decides how to call a factory,
    and whether to clean it up, by its kind. Cleanup — ``close`` or an
    exception thrown in at scope exit — is forwarded to the inner generator.

    Args:
        factory: The factory whose product is mapped.
        fn: Called once per value ``factory`` builds; what it returns is
            what the new factory produces.
        provides: The type the new factory is registered under.
    """
    return _wrap(factory, _evaluated_signature(factory), provides, _unchanged, fn)


def _box_type(index: int) -> type:
    """Return a fresh, private box type for the ``index``-th decoration.

    A decorated service is registered under its box instead of its own type,
    so it never appears in a ``Sequence[T]`` or ``Mapping`` of that type, and
    needs no qualifier of its own. The decorator unboxes it.
    """

    def body(namespace: dict[str, object]) -> None:
        def __init__(self: object, value: object) -> None:  # noqa: N807
            object.__setattr__(self, "value", value)

        namespace["__slots__"] = ("value",)
        namespace["__init__"] = __init__
        namespace["__module__"] = _BOX_MODULE

    box = types.new_class(f"_Inner_{index}", (), exec_body=body)
    # What typing.final records at runtime; the box is never subclassed.
    _set(box, __qualname__=box.__name__, __final__=True)
    return box


def _null_decorator_factory(
    decorator: Callable[..., object] | type,
    inner_parameter: str,
    provides: type,
) -> Callable[..., object]:
    """Return a factory of ``decorator``'s kind with ``inner_parameter`` pre-filled with ``None``.

    Used by the OPTIMIZE pass when a decorator declares
    ``on_invalid=OnInvalid.NULL`` and the decorated service is not defined:
    the decorator is registered under the missing target's key, and this
    wrapper strips its ``AutowireDecorated`` parameter from the signature
    presented to wireup while feeding ``None`` at call time.
    """
    base_factory = (
        _synthesize_class_factory(decorator)
        if isinstance(decorator, type)
        else _clone_function(decorator)
    )
    signature = _evaluated_signature(base_factory)
    if inner_parameter not in signature.parameters:
        msg = f"cannot fill parameter {inner_parameter!r} of {decorator!r} with None"
        raise ValueError(msg)
    parameters = [p for p in signature.parameters.values() if p.name != inner_parameter]

    def fill_none(kwargs: dict[str, object]) -> dict[str, object]:
        kwargs[inner_parameter] = None
        return kwargs

    return _wrap(
        base_factory, signature.replace(parameters=parameters), provides, fill_none, _identity
    )


def _decorating_factory(
    factory: Callable[..., object],
    inner_parameter: str,
    box: type,
    /,
    *,
    provides: object,
) -> Callable[..., object]:
    """Return ``factory`` asking for ``box`` where it asked for ``inner_parameter``.

    wireup injects the boxed inner service; the unboxed value is what
    ``factory`` receives under its own parameter name.

    Raises:
        ValueError: If ``factory`` has no ``inner_parameter``, or already has
            a parameter named like the box.
    """
    signature = _evaluated_signature(factory)
    parameters = list(signature.parameters.values())
    names = [parameter.name for parameter in parameters]
    if inner_parameter not in names or _INNER_BOX_PARAMETER in names:
        msg = f"cannot box parameter {inner_parameter!r} of {factory!r}"
        raise ValueError(msg)
    index = names.index(inner_parameter)
    parameters[index] = inspect.Parameter(
        _INNER_BOX_PARAMETER, inspect.Parameter.KEYWORD_ONLY, annotation=box
    )
    parameters.sort(key=lambda parameter: parameter.kind)

    def unbox(kwargs: dict[str, object]) -> dict[str, object]:
        boxed = kwargs.pop(_INNER_BOX_PARAMETER)
        kwargs[inner_parameter] = cast("object", getattr(boxed, "value"))  # noqa: B009
        return kwargs

    return _wrap(factory, signature.replace(parameters=parameters), provides, unbox, _identity)


def _unchanged(kwargs: dict[str, object]) -> dict[str, object]:
    return kwargs


def _identity(value: object) -> object:
    return value


def _wrap(
    factory: Callable[..., object],
    signature: inspect.Signature,
    provides: object,
    arguments: Callable[[dict[str, object]], Mapping[str, object]],
    result: Callable[[Any], object],
) -> Callable[..., object]:
    """Return a factory of ``factory``'s kind, adapting its arguments and its product."""
    wrapper: Callable[..., object]
    annotation: object = provides
    if inspect.isasyncgenfunction(factory):
        annotation = cast("Any", AsyncIterator)[provides]
        wrapper = _async_generator_wrapper(factory, arguments, result)
    elif inspect.isgeneratorfunction(factory):
        annotation = cast("Any", Iterator)[provides]
        wrapper = _generator_wrapper(factory, arguments, result)
    elif inspect.iscoroutinefunction(factory):
        wrapper = _coroutine_wrapper(factory, arguments, result)
    else:
        wrapper = _plain_wrapper(factory, arguments, result)

    _set(
        wrapper,
        __signature__=to_engine_signature(signature).replace(return_annotation=annotation),
        __annotations__={"return": annotation},
        __module__=factory.__module__,
        __qualname__=getattr(factory, "__qualname__", repr(factory)),
        __name__=getattr(factory, "__name__", repr(factory)),
    )
    return wrapper


def _plain_wrapper(
    factory: Callable[..., object],
    arguments: Callable[[dict[str, object]], Mapping[str, object]],
    result: Callable[[Any], object],
) -> Callable[..., object]:
    def plain(**kwargs: object) -> object:
        return result(factory(**arguments(kwargs)))

    return plain


def _coroutine_wrapper(
    factory: Callable[..., Any],
    arguments: Callable[[dict[str, object]], Mapping[str, object]],
    result: Callable[[Any], object],
) -> Callable[..., object]:
    async def coroutine(**kwargs: object) -> object:
        return result(await factory(**arguments(kwargs)))

    return coroutine


def _generator_wrapper(
    factory: Callable[..., Any],
    arguments: Callable[[dict[str, object]], Mapping[str, object]],
    result: Callable[[Any], object],
) -> Callable[..., object]:
    def generator(**kwargs: object) -> Generator[object, None, None]:
        inner = cast("Generator[object, None, None]", factory(**arguments(kwargs)))
        value = next(inner)
        try:
            mapped = result(value)
        except BaseException:
            inner.close()
            raise
        try:
            yield mapped
        except GeneratorExit:
            inner.close()
            raise
        except BaseException as error:  # noqa: BLE001 — forwarded, not swallowed.
            _throw(inner, error)
        else:
            _ = next(inner, None)

    return generator


def _async_generator_wrapper(
    factory: Callable[..., Any],
    arguments: Callable[[dict[str, object]], Mapping[str, object]],
    result: Callable[[Any], object],
) -> Callable[..., object]:
    async def async_generator(**kwargs: object) -> AsyncGenerator[object, None]:
        inner = cast("AsyncGenerator[object, None]", factory(**arguments(kwargs)))
        value = await inner.__anext__()
        try:
            mapped = result(value)
        except BaseException:
            await inner.aclose()
            raise
        try:
            yield mapped
        except GeneratorExit:
            await inner.aclose()
            raise
        except BaseException as error:  # noqa: BLE001 — forwarded, not swallowed.
            await _athrow(inner, error)
        else:
            _ = await anext(inner, None)

    return async_generator


def _throw(inner: Generator[object, None, None], error: BaseException) -> None:
    """Throw ``error`` into ``inner``, as wireup would have; its own error propagates."""
    try:
        _ = inner.throw(error)
    except StopIteration:
        return


async def _athrow(inner: AsyncGenerator[object, None], error: BaseException) -> None:
    """Throw ``error`` into ``inner``, as wireup would have; its own error propagates."""
    try:
        _ = await inner.athrow(error)
    except StopAsyncIteration:
        return


def _set(target: object, **attributes: object) -> None:
    """Set dunder attributes a synthesized function or type presents to wireup and to readers."""
    for name, value in attributes.items():
        setattr(target, name, value)
