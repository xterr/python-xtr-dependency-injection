from __future__ import annotations

import pytest

from tests.fixtures.app_reset_factory import (
    SlottedSession,  # noqa: TC001 — the container reads the annotation at runtime.
)
from xtr_dependency_injection import Injected, Kernel, bind_callable
from xtr_dependency_injection.exception import InvalidDefinitionError

pytestmark = pytest.mark.anyio


async def test_a_transient_resettable_built_without_weak_references_is_refused() -> None:
    async def handler(session: Injected[SlottedSession]) -> None:
        del session

    kernel = Kernel("tests.fixtures.app_reset_factory", env="test", bundles={})
    async with await kernel.boot() as booted:
        with pytest.raises(InvalidDefinitionError, match="__weakref__"):
            _ = await bind_callable(booted.container, handler, per_call_scope=True)()
