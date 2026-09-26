"""S7: ``bind_callable`` against a real container."""

from __future__ import annotations

from collections.abc import Iterator
from types import FunctionType

import pytest
import wireup
from wireup import Injected

from xtr_dependency_injection import Injected as XtrInjected
from xtr_dependency_injection.runtime import bind_callable
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

pytestmark = pytest.mark.anyio


class Counter:
    built: int = 0


class Greeting:
    text: str = "hello"


class Session:
    def __init__(self) -> None:
        self.closed: bool = False


OPENED: list[Session] = []


def session_resource() -> Iterator[Session]:
    session = Session()
    OPENED.append(session)
    try:
        yield session
    finally:
        session.closed = True


class GreetHandler:
    def __init__(self) -> None:
        Counter.built += 1

    async def __call__(self, name: str, greeting: Injected[Greeting]) -> str:
        return f"{greeting.text} {name}"


async def failing(session: Injected[Session]) -> None:
    raise RuntimeError(str(id(session)))


def add(left: int, right: int) -> int:
    return left + right


async def greet_forward_ref(name: str, greeting: XtrInjected["Greeting"]) -> str:  # noqa: UP037
    return f"{greeting.text} {name}"


def _container(*extra: object) -> WireupContainer:
    engine = wireup.create_async_container(
        injectables=[
            wireup.instance(Greeting(), as_type=Greeting),
            wireup.injectable(GreetHandler),
            *extra,
        ]
    )
    return WireupContainer(engine)


async def test_a_class_target_is_built_lazily_and_its_call_is_filled() -> None:
    Counter.built = 0
    bound = bind_callable(_container(), GreetHandler)
    assert Counter.built == 0

    first = await bound("ada")
    second = await bound("bob")

    assert (first, second) == ("hello ada", "hello bob")
    assert Counter.built == 1


async def test_a_per_call_scope_is_released_even_when_the_call_raises() -> None:
    OPENED.clear()
    container = _container(wireup.injectable(session_resource, lifetime="scoped"))
    bound = bind_callable(container, failing, per_call_scope=True)

    with pytest.raises(RuntimeError):
        _ = await bound()
    with pytest.raises(RuntimeError):
        _ = await bound()

    assert len(OPENED) == 2
    assert OPENED[0] is not OPENED[1]
    assert all(session.closed for session in OPENED)


async def test_a_sync_function_result_is_returned_as_is() -> None:
    bound = bind_callable(_container(), add)

    assert await bound(2, 3) == 5


async def test_a_string_nested_in_injected_is_resolved_at_bind_time() -> None:
    bound = bind_callable(_container(), greet_forward_ref)

    assert await bound("ada") == "hello ada"


def test_the_wrapper_is_named_like_the_target() -> None:
    bound = bind_callable(_container(), add)

    assert isinstance(bound, FunctionType)
    assert bound.__qualname__ == add.__qualname__
    assert bound.__module__ == add.__module__
