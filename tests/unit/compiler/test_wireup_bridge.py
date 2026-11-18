"""The key a factory is registered under, read through the ``type`` aliases its return holds.

``key_type`` must name the key the engine registers the factory's clone under; with an alias
left in the return, the two disagreed — or the build crashed walking the alias's ``__mro__``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from typing import TYPE_CHECKING, Annotated

import pytest

from xtr_dependency_injection.compiler._registration import clone_function
from xtr_dependency_injection.compiler._wireup_bridge import key_type
from xtr_dependency_injection.exception import InvalidArgumentTypeError

if TYPE_CHECKING:
    from types import FunctionType


class Mailer:
    pass


type MailerAlias = Mailer
type Chained = MailerAlias
type MaybeMailer = Mailer | None
type Mailing = Iterator[Mailer]
type AsyncMailing = AsyncIterator[Chained]


def _alias() -> MailerAlias:
    return Mailer()


def _chained() -> Chained:
    return Mailer()


def _optional() -> MaybeMailer:
    return Mailer()


def _optional_of_alias() -> MailerAlias | None:
    return Mailer()


def _annotated() -> Annotated[MailerAlias, "kept"]:
    return Mailer()


async def _coroutine() -> MailerAlias:
    return Mailer()


def _iterator_of_alias() -> Iterator[MailerAlias]:
    yield Mailer()


def _aliased_iterator() -> Mailing:
    yield Mailer()


async def _aliased_async_iterator() -> AsyncMailing:
    yield Mailer()


def _plain() -> Mailer:
    return Mailer()


def _plain_iterator() -> Iterator[Mailer]:
    yield Mailer()


KEYS: list[tuple[FunctionType, object]] = [
    (_alias, Mailer),
    (_chained, Mailer),
    (_optional, Mailer | None),
    (_optional_of_alias, Mailer | None),
    (_annotated, Mailer),
    (_coroutine, Mailer),
    (_iterator_of_alias, Mailer),
    (_aliased_iterator, Mailer),
    (_aliased_async_iterator, Mailer),
    (_plain, Mailer),
    (_plain_iterator, Mailer),
]
ALIASED: list[FunctionType] = [factory for factory, _ in KEYS[:9]]
PLAIN: list[FunctionType] = [_plain, _plain_iterator]


@pytest.mark.parametrize(("factory", "key"), KEYS, ids=[factory.__name__ for factory, _ in KEYS])
def test_a_factory_is_keyed_by_what_its_return_stands_for(
    factory: Callable[..., object], key: object
) -> None:
    assert key_type(factory) == key


def test_a_generator_without_a_yielded_type_still_has_no_key() -> None:
    # The case under test: an iterator naming nothing it yields.
    def bare() -> Iterator:  # pyright: ignore[reportMissingTypeArgument, reportUnknownParameterType]
        yield Mailer()

    with pytest.raises(InvalidArgumentTypeError, match="must annotate its return type"):
        _ = key_type(bare)  # pyright: ignore[reportUnknownArgumentType] — the case under test


@pytest.mark.parametrize("factory", ALIASED, ids=[factory.__name__ for factory in ALIASED])
def test_the_clone_carries_the_return_the_key_was_read_from(
    factory: Callable[..., object],
) -> None:
    clone = clone_function(factory)

    assert key_type(clone) == key_type(factory)
    assert clone.__annotations__["return"] != factory.__annotations__["return"]


@pytest.mark.parametrize("factory", PLAIN, ids=[factory.__name__ for factory in PLAIN])
def test_the_clone_of_an_alias_free_factory_keeps_its_return_as_written(
    factory: Callable[..., object],
) -> None:
    clone = clone_function(factory)

    # Written as a string here, under the future import, and left so.
    assert clone.__annotations__["return"] == factory.__annotations__["return"]
