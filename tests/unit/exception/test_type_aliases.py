"""Every shape an annotation reads through its ``type`` aliases in, and every shape left alone.

The engine under the container knows nothing of :class:`typing.TypeAliasType`: an alias left
in an annotation names a service no one registered, or hides the marker saying the container
fills a parameter. :func:`without_type_aliases` is what every annotation the container reads
goes through, so each case here is one the container must read as the alias's value — or,
holding no alias, must read exactly as written.
"""

from __future__ import annotations

import inspect
import operator
from collections.abc import AsyncIterator, Callable, Hashable, Iterator, Mapping, Sequence
from types import GenericAlias
from typing import Annotated, Any, Literal, TypeAliasType, TypeVar, cast, get_args

import pytest

from xtr_dependency_injection import Autowire, Injected, ServiceLocator, Target
from xtr_dependency_injection.exception._signatures import evaluated_signature
from xtr_dependency_injection.exception._type_aliases import (
    signature_without_type_aliases,
    without_type_aliases,
)

T = TypeVar("T")


class Mailer:
    pass


class Smtp(Mailer):
    pass


type MailerAlias = Mailer
type Chained = MailerAlias
type ChainedTwice = Chained
type InjectedMailer = Injected[Mailer]
type TargetedMailer = Annotated[Mailer, Target("smtp")]
type OptionalMailer = Mailer | None
type Mailers = Sequence[Mailer]
type MailersByName = Mapping[Hashable, Mailer]
type MailerLocator = ServiceLocator[Mailer]
type Environment = Annotated[str, Autowire(param="kernel.environment")]
type Format = Literal["txt", "json"]
type Qualified[S] = Annotated[S, Target("smtp")]
type Swapped[K, V] = dict[V, K]
type Itself[S] = S
type Ignored[S] = Mailer
type Boxed[S] = ServiceLocator[S]
type Variadic[*Vs] = tuple[*Vs]
type Json = dict[str, Json] | list[Json] | str
type Ping = list[Pong] | int
type Pong = list[Ping] | str
type Tree[S] = S | list[Tree[S]]
type Mailing = Iterator[Mailer]


def _variadic[*Us]() -> object:
    """``tuple[*Us]``, its type variable bound where the checkers read it."""
    return tuple[*Us]


def _param_spec[**Q]() -> tuple[object, object, object]:
    """``Callable[Q, ...]`` with an alias, its expansion, and one with none."""
    return Callable[Q, MailerAlias], Callable[Q, Mailer], Callable[Q, Mailer]


# Annotations as values, handed to the function under test: plain expressions, not aliases.
OptionalTargeted = Annotated[Mailer, Target("smtp")] | None
OptionalAliasedMarker = InjectedMailer | None
OptionalInjected = Injected[Mailer] | None
ALIASED_PARAM_SPEC, EXPANDED_PARAM_SPEC, PLAIN_PARAM_SPEC = _param_spec()

ALIAS_FREE: tuple[object, ...] = (
    Mailer,
    None,
    Any,
    T,
    "Mailer",
    Mailer | None,
    Injected[Mailer],
    Annotated[Mailer, Target("smtp")],
    OptionalTargeted,
    Sequence[Mailer],
    Mapping[Hashable, Mailer],
    ServiceLocator[Mailer],
    dict[str, int],
    tuple[int, ...],
    _variadic(),
    type[Mailer],
    Callable[[int, str], Mailer],
    Callable[..., Mailer],
    PLAIN_PARAM_SPEC,
    Iterator[Mailer],
    AsyncIterator[Mailer],
    Literal["txt", "json"],
    Literal[1, 2],
)


@pytest.mark.parametrize("annotation", ALIAS_FREE, ids=repr)
def test_an_annotation_without_an_alias_is_returned_as_the_same_object(annotation: object) -> None:
    assert without_type_aliases(annotation) is annotation


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (MailerAlias, Mailer),
        (Chained, Mailer),
        (ChainedTwice, Mailer),
        (InjectedMailer, Injected[Mailer]),
        (TargetedMailer, Annotated[Mailer, Target("smtp")]),
        (OptionalMailer, Mailer | None),
        (Mailers, Sequence[Mailer]),
        (MailersByName, Mapping[Hashable, Mailer]),
        (MailerLocator, ServiceLocator[Mailer]),
        (Environment, Annotated[str, Autowire(param="kernel.environment")]),
        (Format, Literal["txt", "json"]),
        (Mailing, Iterator[Mailer]),
    ],
    ids=repr,
)
def test_an_alias_reads_as_what_it_stands_for(annotation: object, expected: object) -> None:
    assert without_type_aliases(annotation) == expected


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (Injected[MailerAlias], Injected[Mailer]),
        (Annotated[MailerAlias, Target("smtp")], Annotated[Mailer, Target("smtp")]),
        (Annotated[Chained, Target("smtp"), "kept"], Annotated[Mailer, Target("smtp"), "kept"]),
        (MailerAlias | None, Mailer | None),
        (OptionalAliasedMarker, OptionalInjected),
        (MailerAlias | int, Mailer | int),
        (Sequence[MailerAlias], Sequence[Mailer]),
        (Mapping[Hashable, MailerAlias], Mapping[Hashable, Mailer]),
        (ServiceLocator[MailerAlias], ServiceLocator[Mailer]),
        (Injected[ServiceLocator[MailerAlias]], Injected[ServiceLocator[Mailer]]),
        (dict[str, MailerAlias], dict[str, Mailer]),
        (tuple[MailerAlias, ...], tuple[Mailer, ...]),
        (type[MailerAlias], type[Mailer]),
        (Callable[[MailerAlias], MailerAlias], Callable[[Mailer], Mailer]),
        (Callable[..., MailerAlias], Callable[..., Mailer]),
        (ALIASED_PARAM_SPEC, EXPANDED_PARAM_SPEC),
        (Iterator[MailerAlias], Iterator[Mailer]),
        (AsyncIterator[Chained], AsyncIterator[Mailer]),
        (list[Sequence[MailerAlias]], list[Sequence[Mailer]]),
    ],
    ids=repr,
)
def test_an_alias_nested_anywhere_reads_as_what_it_stands_for(
    annotation: object, expected: object
) -> None:
    assert without_type_aliases(annotation) == expected


def test_an_alias_of_a_marker_inside_annotated_keeps_every_marker() -> None:
    expanded = without_type_aliases(Annotated[InjectedMailer, Target("smtp")])

    assert expanded == Annotated[Mailer, Autowire(), Target("smtp")]


def test_a_union_an_alias_makes_redundant_collapses() -> None:
    assert without_type_aliases(MailerAlias | Mailer) is Mailer


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        (Qualified[Mailer], Annotated[Mailer, Target("smtp")]),
        (Qualified[MailerAlias], Annotated[Mailer, Target("smtp")]),
        (Swapped[int, str], dict[str, int]),
        (Itself[Mailer], Mailer),
        (Itself[MailerAlias], Mailer),
        (Ignored[int], Mailer),
        (Boxed[Mailer], ServiceLocator[Mailer]),
        (Sequence[Qualified[Mailer]], Sequence[Annotated[Mailer, Target("smtp")]]),
    ],
    ids=repr,
)
def test_an_applied_alias_substitutes_its_arguments_by_name(
    annotation: object, expected: object
) -> None:
    assert without_type_aliases(annotation) == expected


def test_an_alias_over_a_variadic_parameter_is_left_as_written() -> None:
    alias: TypeAliasType = Variadic
    applied = alias[int, str]

    assert without_type_aliases(applied) is applied


def test_an_alias_applied_to_the_wrong_count_of_arguments_is_left_as_written() -> None:
    alias: TypeAliasType = Swapped
    # Built at run time: the checkers refuse the wrong count written out, rightly.
    applied = operator.getitem(alias, int)

    assert without_type_aliases(applied) is applied


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        (Json, dict[str, Json] | list[Json] | str),
        # Each alias opens once along a path: Ping through Pong, back to Ping, and stops.
        (Ping, list[list[Ping] | str] | int),
        (Pong, list[list[Pong] | int] | str),
    ],
    ids=repr,
)
def test_a_recursive_alias_is_expanded_once_along_each_path_and_ends(
    alias: object, expected: object
) -> None:
    assert without_type_aliases(alias) == expected


def test_a_recursive_alias_keeps_itself_where_it_recurses() -> None:
    members = get_args(without_type_aliases(Json))

    assert members == (dict[str, Json], list[Json], str)


def test_a_recursive_applied_alias_ends() -> None:
    expanded = without_type_aliases(Tree[Mailer])

    assert get_args(expanded)[0] is Mailer


def test_a_literal_is_never_read_as_types() -> None:
    literal = Literal["MailerAlias"]

    assert without_type_aliases(literal) is literal


class Picky:
    """A form of its own that takes an alias but refuses a class."""

    def __class_getitem__(cls, item: object) -> object:
        if isinstance(item, type):
            msg = "Picky takes no class"
            raise TypeError(msg)
        return GenericAlias(cls, item)


def test_a_form_refusing_what_an_alias_stands_for_is_left_as_written() -> None:
    picky = Picky[MailerAlias]

    assert without_type_aliases(picky) is picky


S = TypeVar("S")
# Aliases no type checker accepts, built the way a ``type`` statement builds one, at run time.
_alias_of = cast("Callable[..., TypeAliasType]", TypeAliasType)
OUTER = _alias_of("Outer", GenericAlias(dict, (S, T)), type_params=(S,))
NOT_A_TYPE = _alias_of("NotAType", 3)


def test_an_alias_naming_a_variable_it_does_not_declare_is_left_as_written() -> None:
    applied = operator.getitem(OUTER, int)

    assert without_type_aliases(applied) is applied


def test_an_alias_of_a_value_reads_as_the_value() -> None:
    assert get_args(without_type_aliases(NOT_A_TYPE | int)) == (3, int)


def _uses(mailer: MailerAlias, fmt: Format, plain: int = 1) -> Mailers:
    del mailer, fmt, plain
    return []


def _plain(mailer: Mailer, count: int = 0) -> Sequence[Mailer]:
    del mailer, count
    return []


def _annotation(signature: inspect.Signature, name: str) -> object:
    return cast("object", signature.parameters[name].annotation)


def _returned(signature: inspect.Signature) -> object:
    return cast("object", signature.return_annotation)


def test_a_signature_reads_every_parameter_and_its_return_through_aliases() -> None:
    signature = signature_without_type_aliases(inspect.signature(_uses, eval_str=True))

    annotations = {name: _annotation(signature, name) for name in signature.parameters}
    assert annotations == {"mailer": Mailer, "fmt": Literal["txt", "json"], "plain": int}
    assert _returned(signature) == Sequence[Mailer]


def test_a_signature_without_an_alias_is_returned_as_the_same_object() -> None:
    signature = inspect.signature(_plain, eval_str=True)

    assert signature_without_type_aliases(signature) is signature


def test_a_signature_keeps_defaults_kinds_and_order() -> None:
    signature = signature_without_type_aliases(inspect.signature(_uses, eval_str=True))

    shape = [(p.name, p.kind, cast("object", p.default)) for p in signature.parameters.values()]
    assert shape == [
        ("mailer", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("fmt", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty),
        ("plain", inspect.Parameter.POSITIONAL_OR_KEYWORD, 1),
    ]


class Service:
    def __init__(self, mailer: Annotated[MailerAlias, Target("smtp")], mailers: Mailers) -> None:
        del mailer, mailers


def test_the_evaluated_signature_of_a_class_reads_through_aliases() -> None:
    signature = evaluated_signature(Service)

    assert _annotation(signature, "mailer") == Annotated[Mailer, Target("smtp")]
    assert _annotation(signature, "mailers") == Sequence[Mailer]


def test_the_evaluated_signature_of_a_function_reads_its_return_through_aliases() -> None:
    signature = evaluated_signature(_uses)

    assert _annotation(signature, "mailer") is Mailer
    assert _returned(signature) == Sequence[Mailer]


def test_the_evaluated_signature_of_an_alias_free_function_is_unchanged() -> None:
    signature = evaluated_signature(_plain)

    assert _annotation(signature, "mailer") is Mailer
    assert _returned(signature) == Sequence[Mailer]
