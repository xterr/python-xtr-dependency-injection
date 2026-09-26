"""Building a fully-evaluated signature, including strings nested in ``Annotated``.

``inspect.signature(obj, eval_str=True)`` evaluates a top-level string
annotation, but leaves a string *nested* inside ``Annotated[...]`` a
``ForwardRef``: on Python 3.14 ``Annotated["Dep", Target("x")]`` reads back as
``Annotated[ForwardRef('Dep'), Target('x')]``. wireup then takes the
``ForwardRef`` for the dependency's type and the container fails to compile
("unknown dependency on ForwardRef('Dep')"), and a decorator's
``Annotated["Mailer | None", AutowireDecorated()]`` is rejected because the
``ForwardRef`` is not the decorated type.

``typing.get_type_hints(obj, include_extras=True)`` resolves those nested
strings against the object's own module. This one helper marries the two: the
``eval_str`` signature for parameter kinds, defaults and order, and the hints
for the annotations. It lives in the leaf ``exception`` layer so the compiler,
the decorators and the runtime can all read a caller's annotations the same
way, and the fix lives in one spot.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, get_type_hints

from ._naming import ANNOTATION_HINT, qualified_name

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = ["evaluated_signature"]


def evaluated_signature(
    target: Callable[..., object] | type,
    /,
    *,
    context: str | None = None,
) -> inspect.Signature:
    """Return ``target``'s signature with every annotation fully evaluated.

    Parameter kinds, defaults and order come from
    ``inspect.signature(target, eval_str=True)``; each annotation is then
    replaced by the resolved hint from
    ``typing.get_type_hints(..., include_extras=True)`` (a class reads its
    ``__init__`` hints), so a string nested in ``Annotated[...]`` no longer
    leaks a ``ForwardRef``.

    Args:
        target: The class or callable whose signature to read.
        context: Names ``target`` in the ``NameError`` note; defaults to
            ``reading the signature of <target>``.

    Raises:
        NameError: If an annotation names something not importable at runtime;
            the note carries :data:`ANNOTATION_HINT`.
    """
    try:
        signature = inspect.signature(target, eval_str=True)
        annotations = _resolved_annotations(target)
    except NameError as error:
        clause = context or f"reading the signature of {qualified_name(target)}"
        error.add_note(f"while {clause}: {ANNOTATION_HINT}")
        raise
    if not annotations:
        return signature
    parameters = [
        parameter.replace(annotation=annotations[name]) if name in annotations else parameter
        for name, parameter in signature.parameters.items()
    ]
    return signature.replace(parameters=parameters)


def _resolved_annotations(target: Callable[..., object] | type) -> Mapping[str, object]:
    """Return resolved parameter annotations, or empty when the signature is authoritative.

    A synthesized factory carries an already-resolved ``__signature__`` and, on
    it, the pre-rewrite original annotations; honoring that signature and
    skipping the hints keeps the engine markers the synthesizer wrote. A class
    reads its ``__init__`` hints; anything else reads its own.
    """
    if hasattr(target, "__signature__"):
        return {}
    source: object = target.__init__ if isinstance(target, type) else target
    return get_type_hints(source, include_extras=True)
