from __future__ import annotations

import pytest

from tests.fixtures.app_marked import EmailNotifier, Notifier, Widget
from xtr_dependency_injection.kernel import Kernel

pytestmark = pytest.mark.anyio


async def test_as_service_class_is_registered_under_its_own_type() -> None:
    compiled = Kernel("tests.fixtures.app_marked", bundles={}).build()

    async with await compiled.boot() as booted:
        got = await booted.container.get(EmailNotifier)

    assert isinstance(got, EmailNotifier)


async def test_as_service_factory_is_registered_under_its_return_type() -> None:
    compiled = Kernel("tests.fixtures.app_marked", bundles={}).build()

    async with await compiled.boot() as booted:
        got = await booted.container.get(Widget)

    assert isinstance(got, Widget)


async def test_as_alias_resolves_to_the_same_singleton_as_the_target() -> None:
    compiled = Kernel("tests.fixtures.app_marked", bundles={}).build()

    async with await compiled.boot() as booted:
        through_alias = await booted.container.get(Notifier)
        through_target = await booted.container.get(EmailNotifier)

    assert through_alias is through_target
