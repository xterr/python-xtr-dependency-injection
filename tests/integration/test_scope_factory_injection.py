"""A service injects ``ScopeFactoryInterface`` to open a unit of work, not the container.

End-to-end against a real kernel: the kernel registers the scope factory, a
service receives it instead of the whole container, and the unit it opens
builds and releases a scoped service.
"""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,  # noqa: TC003 — the engine reads the factory's return annotation
)
from typing import TYPE_CHECKING, final

import pytest
from typing_extensions import override

from xtr_dependency_injection import (
    Bundle,
    Kernel,
    ScopeFactoryInterface,
    ServiceConfigurator,
    as_bundle,
)

if TYPE_CHECKING:
    from xtr_dependency_injection import CompiledKernel
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

pytestmark = pytest.mark.anyio


@final
class Session:
    """A scoped service recording whether it was released."""

    def __init__(self) -> None:
        self.closed = False


async def _session_factory() -> AsyncIterator[Session]:
    session = Session()
    try:
        yield session
    finally:
        session.closed = True


@final
class Worker:
    """A service that opens a unit of work through the injected factory."""

    def __init__(self, scopes: ScopeFactoryInterface) -> None:
        self.scopes = scopes

    async def run(self) -> Session:
        async with self.scopes.unit_of_work() as unit:
            return await unit.get(Session)


@final
@as_bundle("scopes")
class ScopesBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.set(_session_factory, lifetime="scoped")
        _ = services.set(Worker)


def _compiled() -> CompiledKernel:
    return Kernel("json", resources=(), bundles={ScopesBundle: {"all": True}}).build()


async def test_the_kernel_registers_the_scope_factory() -> None:
    async with await _compiled().boot() as booted:
        assert isinstance(await booted.container.get(ScopeFactoryInterface), ScopeFactoryInterface)


async def test_a_service_opens_a_unit_of_work_through_the_injected_factory() -> None:
    async with await _compiled().boot() as booted:
        worker = await booted.container.get(Worker)

        session = await worker.run()

        assert session.closed
