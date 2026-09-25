"""Calling a handler, a command or any callable with the container filling it in.

Both the message bus and the console need the same thing from a container:
call something the application declared, passing what the caller has — the
message, the parsed arguments — and letting the container supply every
``Injected[...]`` parameter. A class target is a service: it is built by the
container, once, on first use, and its ``__call__`` is what gets filled.
"""

from __future__ import annotations

import inspect
from contextvars import ContextVar
from typing import TYPE_CHECKING, cast

import wireup

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from wireup import AsyncContainer, ScopedAsyncContainer

__all__ = ["bind_callable"]

_ANNOTATION_HINT = "import annotation types at runtime, not under TYPE_CHECKING"

# The scope of the bound call running in this context. One variable serves
# every binding: calls nest, and each call restores what it replaced.
_scope: ContextVar[ScopedAsyncContainer] = ContextVar("xtr_dependency_injection_scope")


def bind_callable(
    container: AsyncContainer,
    target: Callable[..., object] | type,
    /,
    *,
    per_call_scope: bool = False,
    signature: inspect.Signature | None = None,
) -> Callable[..., Awaitable[object]]:
    """Return a coroutine function calling ``target``, its injections filled from ``container``.

    What ``target`` needs is checked now, against ``container``: a bundle
    binding its handlers as it boots fails there, not on the first message.

    Args:
        container: Where dependencies come from.
        target: A function, or a class registered with the container, whose
            instances are called. The class is resolved lazily, on the
            first call.
        per_call_scope: Enter a scope for every call, releasing what was
            scoped to it when the call ends — even if it raised. Without it,
            wireup enters one only when an ``Injected[...]`` parameter needs
            it, and the class itself is resolved from the root container.
        signature: The signature to present to wireup instead of
            ``target``'s own (the ``__call__``'s, without ``self``, for a
            class), with its annotations already evaluated.

    Returns:
        A coroutine function taking what ``target`` takes, minus what is
        injected. A synchronous result is returned as is.

    Raises:
        TypeError: If ``target`` is a class without ``__call__``.
        WireupError: If ``target`` asks for something ``container`` cannot
            provide.
    """
    presented = signature if signature is not None else _signature_of(target)
    is_class = isinstance(target, type)

    async def entry(*args: object, **kwargs: object) -> object:
        call: Callable[..., object]
        if is_class:
            source = _scope.get() if per_call_scope else container
            call = cast("Callable[..., object]", await source.get(target))
        else:
            call = target
        result = call(*args, **kwargs)
        return await cast("Awaitable[object]", result) if inspect.isawaitable(result) else result

    _name_like(entry, target)
    setattr(entry, "__signature__", presented)  # noqa: B010 — read by wireup through inspect.signature.

    bound: Callable[..., Awaitable[object]]
    if per_call_scope:
        injected = wireup.inject_from_container(container, scoped_container_supplier=_scope.get)(
            entry
        )

        async def scoped(*args: object, **kwargs: object) -> object:
            async with container.enter_scope() as scope:
                token = _scope.set(scope)
                try:
                    return await injected(*args, **kwargs)
                finally:
                    _scope.reset(token)

        bound = scoped
    else:
        bound = wireup.inject_from_container(container)(entry)

    _name_like(bound, target)
    return bound


def _signature_of(target: Callable[..., object] | type) -> inspect.Signature:
    """Return what calling ``target`` takes, annotations evaluated against its module.

    For a class, that is its ``__call__`` without ``self``.

    Raises:
        TypeError: If ``target`` is a class without ``__call__``.
        NameError: If an annotation is not importable at runtime.
    """
    callable_target: Callable[..., object] = target
    if isinstance(target, type):
        declared = next(
            (vars(klass)["__call__"] for klass in target.__mro__[:-1] if "__call__" in vars(klass)),
            None,
        )
        if declared is None:
            msg = f"{target.__qualname__} has no __call__ to bind"
            raise TypeError(msg)
        callable_target = cast("Callable[..., object]", declared)
    try:
        signature = inspect.signature(callable_target, eval_str=True)
    except NameError as error:
        error.add_note(f"while binding {_qualname(target)}: {_ANNOTATION_HINT}")
        raise
    if isinstance(target, type):
        parameters = list(signature.parameters.values())[1:]
        signature = signature.replace(parameters=parameters)
    return signature


def _name_like(wrapper: Callable[..., object], target: Callable[..., object] | type) -> None:
    """Name ``wrapper`` after ``target``, so an error wireup raises points at ``target``."""
    for attribute in ("__name__", "__qualname__", "__module__"):
        if hasattr(target, attribute):
            setattr(wrapper, attribute, getattr(target, attribute))


def _qualname(target: object) -> str:
    return cast("str", getattr(target, "__qualname__", repr(target)))
