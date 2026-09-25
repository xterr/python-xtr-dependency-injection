from __future__ import annotations

import pytest
import wireup

from xtr_dependency_injection.exception import UnknownLocatorKeyError
from xtr_dependency_injection.runtime import ServiceLocator

pytestmark = pytest.mark.anyio


class Middleware:
    built: int = 0

    def __init__(self) -> None:
        Middleware.built += 1


class LoggingMiddleware(Middleware):
    pass


class TracingMiddleware(Middleware):
    pass


def _locator() -> ServiceLocator[Middleware]:
    container = wireup.create_async_container(
        injectables=[
            wireup.injectable(LoggingMiddleware, as_type=Middleware, qualifier="logging"),
            wireup.injectable(TracingMiddleware, as_type=Middleware, qualifier="tracing"),
        ]
    )
    return ServiceLocator(
        container, {"logging": (Middleware, "logging"), "tracing": (Middleware, "tracing")}
    )


async def test_only_the_service_asked_for_is_built() -> None:
    Middleware.built = 0
    locator = _locator()

    first = await locator.get("logging")
    again = await locator.get("logging")

    assert first is again
    assert Middleware.built == 1


def test_membership_and_keys() -> None:
    locator = _locator()

    assert "logging" in locator
    assert "absent" not in locator
    assert list(locator.keys()) == ["logging", "tracing"]


async def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(UnknownLocatorKeyError) as caught:
        _ = await _locator().get("absent")

    assert caught.value.known == ("logging", "tracing")
