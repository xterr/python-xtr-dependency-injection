from __future__ import annotations

import pytest

from tests.fixtures.app_reset_factory import (
    SlottedSession,  # noqa: TC001 — the container reads the annotation at runtime.
)
from xtr_dependency_injection import Injected, Kernel, ServicesResetter, bind_callable

pytestmark = pytest.mark.anyio


async def test_a_transient_resettable_built_without_weak_references_is_not_tracked() -> None:
    built: list[SlottedSession] = []

    async def handler(session: Injected[SlottedSession]) -> None:
        session.entries.append("kept")
        built.append(session)

    kernel = Kernel("tests.fixtures.app_reset_factory", env="test", bundles={})
    async with await kernel.boot() as booted:
        _ = await bind_callable(booted.container, handler, per_call_scope=True)()
        await (await booted.container.get(ServicesResetter)).reset()

    assert built[0].entries == ["kept"]
