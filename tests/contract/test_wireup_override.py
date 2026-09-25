"""S8: ``container.override.set`` replaces a singleton not yet built."""

from __future__ import annotations

import pytest
import wireup
from wireup import Injected

pytestmark = pytest.mark.anyio


class Mailer:
    name: str = "real"


class FakeMailer(Mailer):
    name: str = "fake"


async def send(mailer: Injected[Mailer]) -> str:
    return mailer.name


async def test_an_override_replaces_an_unbuilt_singleton() -> None:
    container = wireup.create_async_container(injectables=[wireup.injectable(Mailer)])
    fake = FakeMailer()

    container.override.set(Mailer, fake)

    assert await container.get(Mailer) is fake


async def test_an_override_is_seen_by_an_injected_function() -> None:
    container = wireup.create_async_container(
        injectables=[wireup.injectable(Mailer, qualifier="smtp"), wireup.injectable(Mailer)]
    )
    injected = wireup.inject_from_container(container)(send)

    container.override.set(Mailer, FakeMailer())

    assert await injected() == "fake"


async def test_a_qualified_override_is_set_by_its_qualifier() -> None:
    container = wireup.create_async_container(
        injectables=[wireup.injectable(Mailer, qualifier="smtp")]
    )
    fake = FakeMailer()

    container.override.set(Mailer, fake, qualifier="smtp")

    assert await container.get(Mailer, "smtp") is fake
