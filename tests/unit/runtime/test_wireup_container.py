"""``WireupContainer`` implements the :class:`ContainerInterface` seam.

Every consumer sees this — bundles as ``self.container``, ``bind_callable``,
service locators — never the engine directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import pytest
import wireup
from typing_extensions import override
from wireup.errors import WireupError
from xtr_service_contracts import ContainerInterface

from xtr_dependency_injection import Bundle, Kernel, ServiceConfigurator, as_bundle
from xtr_dependency_injection.exception import (
    ContainerCompilationError,
    ParameterNotFoundError,
    ServiceNotFoundError,
    ServiceResolutionError,
)
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

pytestmark = pytest.mark.anyio


@wireup.injectable
class Registered:
    pass


class NotRegistered:
    pass


async def test_has_returns_true_for_a_registered_service() -> None:
    engine = wireup.create_async_container(injectables=[Registered])
    container = WireupContainer(engine)

    assert container.has(Registered)
    assert not container.has(NotRegistered)


async def test_get_of_an_unregistered_service_is_a_lookup_error() -> None:
    engine = wireup.create_async_container()
    container = WireupContainer(engine)

    with pytest.raises(ServiceNotFoundError) as caught:
        _ = await container.get(NotRegistered)
    assert isinstance(caught.value, LookupError)


async def test_get_returns_the_registered_service() -> None:
    engine = wireup.create_async_container(injectables=[Registered])
    container = WireupContainer(engine)

    obtained = await container.get(Registered)

    assert isinstance(obtained, Registered)


async def test_get_parameter_returns_a_kernel_parameter() -> None:
    engine = wireup.create_async_container(
        config={"kernel": {"environment": "dev", "name": "shop"}},
    )
    container = WireupContainer(engine)

    assert container.get_parameter("kernel.environment") == "dev"
    assert container.get_parameter("kernel.name") == "shop"
    assert container.has_parameter("kernel.environment")


async def test_get_parameter_of_an_unset_name_is_a_lookup_error() -> None:
    engine = wireup.create_async_container(config={"kernel": {"environment": "dev"}})
    container = WireupContainer(engine)

    assert not container.has_parameter("kernel.nope")
    with pytest.raises(ParameterNotFoundError) as caught:
        _ = container.get_parameter("kernel.nope")
    assert isinstance(caught.value, LookupError)


async def test_wireup_container_is_a_container_interface() -> None:
    engine = wireup.create_async_container()

    container = WireupContainer(engine)

    assert isinstance(container, ContainerInterface)


async def test_kernel_built_container_interface_is_the_same_wireup_container() -> None:
    booted = await Kernel("json", resources=(), bundles={}).boot()
    try:
        obtained = await booted.container.get(ContainerInterface)

        assert isinstance(obtained, WireupContainer)
        assert obtained.has(ContainerInterface)
        assert obtained.get_parameter("kernel.name") == "json"
    finally:
        await booted.shutdown()


@final
class NeedsAnUnknownDep:
    def __init__(self, missing: NotRegistered) -> None:
        self.missing = missing


def test_a_bad_definition_surfaces_as_container_compilation_error() -> None:
    @as_bundle("bad")
    class BadBundle(Bundle):
        @override
        def load_extension(
            self,
            config: object,
            services: ServiceConfigurator,
            builder: ContainerBuilder,
        ) -> None:
            del config, builder
            _ = services.set(NeedsAnUnknownDep)

    kernel = Kernel("json", resources=(), bundles={BadBundle: {"all": True}})

    with pytest.raises(ContainerCompilationError) as caught:
        _ = kernel.build()

    assert isinstance(caught.value.__cause__, WireupError)


class BoomError(Exception):
    pass


class BuiltFromBrokenFactory:
    pass


def broken_factory() -> BuiltFromBrokenFactory:
    raise BoomError("factory blew up")


async def test_engine_failure_while_building_surfaces_as_service_resolution_error() -> None:
    engine = wireup.create_async_container(
        injectables=[wireup.injectable(broken_factory)],
    )
    container = WireupContainer(engine)

    with pytest.raises(ServiceResolutionError) as caught:
        _ = await container.get(BuiltFromBrokenFactory)

    assert isinstance(caught.value.__cause__, BoomError)
    assert "factory blew up" in caught.value.reason
    assert "factory blew up" in str(caught.value)


class Session:
    pass


def session_factory() -> Session:
    return Session()


async def test_resolving_a_scoped_service_from_the_root_advises_how_to_scope() -> None:
    engine = wireup.create_async_container(
        injectables=[wireup.injectable(session_factory, lifetime="scoped")],
    )
    container = WireupContainer(engine)

    with pytest.raises(ServiceResolutionError) as caught:
        _ = await container.get(Session)

    assert isinstance(caught.value.__cause__, WireupError)
    assert "per_call_scope=True" in str(caught.value)
    assert "scoped and transient" in str(caught.value)
