"""``ServiceLocator`` is a ``ServiceCollectionInterface`` built from a ``ContainerInterface``.

The locator is tested against a dict-backed fake ``ContainerInterface``
(no engine): laziness, iteration order, len, provided_services, has/in,
isinstance and unknown-name errors are container-agnostic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar, cast, final

import pytest
from typing_extensions import override
from xtr_service_contracts import (
    ContainerInterface,
    ServiceCollectionInterface,
    ServiceProviderInterface,
)

from xtr_dependency_injection import Bundle, Kernel, ServiceConfigurator, as_bundle
from xtr_dependency_injection.exception import UnknownLocatorKeyError
from xtr_dependency_injection.runtime import ServiceLocator

if TYPE_CHECKING:
    from collections.abc import Hashable

pytestmark = pytest.mark.anyio

T = TypeVar("T")


@final
class Middleware:
    built: int = 0
    label: str

    def __init__(self, label: str) -> None:
        self.label = label
        Middleware.built += 1


class FakeContainer(ContainerInterface):
    """A dict-backed :class:`ContainerInterface` — no engine, no wireup."""

    _services: dict[tuple[type[object], Hashable | None], object]

    def __init__(self, services: dict[tuple[type[object], Hashable | None], object]) -> None:
        self._services = services

    @override
    async def get(self, service: type[T], /, qualifier: Hashable | None = None) -> T:
        return cast("T", self._services[(service, qualifier)])

    @override
    def has(self, service: type[object], /, qualifier: Hashable | None = None) -> bool:
        return (service, qualifier) in self._services

    @override
    def get_parameter(self, name: str, /) -> object:
        del name
        raise NotImplementedError

    @override
    def has_parameter(self, name: str, /) -> bool:
        del name
        return False


def _built(builds: list[str], label: str) -> Middleware:
    builds.append(label)
    return Middleware(label)


def _locator(builds: list[str]) -> ServiceLocator[Middleware]:
    services: dict[tuple[type[object], Hashable | None], object] = {
        (Middleware, "logging"): _built(builds, "logging_built"),
        (Middleware, "tracing"): _built(builds, "tracing_built"),
    }
    builds.clear()
    container = FakeContainer(services)
    return ServiceLocator(
        container, {"logging": (Middleware, "logging"), "tracing": (Middleware, "tracing")}
    )


async def test_only_the_service_asked_for_is_built() -> None:
    calls: list[str] = []

    class CountingContainer(FakeContainer):
        @override
        async def get(self, service: type[T], /, qualifier: Hashable | None = None) -> T:
            calls.append(str(qualifier))
            return await super().get(service, qualifier)

    services: dict[tuple[type[object], Hashable | None], object] = {
        (Middleware, "logging"): Middleware("logging"),
        (Middleware, "tracing"): Middleware("tracing"),
    }
    container = CountingContainer(services)
    locator = ServiceLocator[Middleware](
        container, {"logging": (Middleware, "logging"), "tracing": (Middleware, "tracing")}
    )

    first = await locator.get("logging")
    again = await locator.get("logging")

    assert first is again
    assert calls == ["logging", "logging"]


def test_membership_uses_has() -> None:
    locator = _locator([])

    assert "logging" in locator
    assert "absent" not in locator
    assert locator.has("logging")
    assert not locator.has("absent")


def test_len_reports_entry_count() -> None:
    assert len(_locator([])) == 2


def test_provided_services_names_each_entrys_type() -> None:
    locator = _locator([])

    provided = locator.provided_services()

    assert dict(provided) == {"logging": Middleware, "tracing": Middleware}


async def test_aiter_yields_pairs_in_entry_order_and_lazily() -> None:
    calls: list[Hashable] = []

    class CountingContainer(FakeContainer):
        @override
        async def get(self, service: type[T], /, qualifier: Hashable | None = None) -> T:
            calls.append(qualifier)
            return await super().get(service, qualifier)

    services: dict[tuple[type[object], Hashable | None], object] = {
        (Middleware, "logging"): Middleware("logging"),
        (Middleware, "tracing"): Middleware("tracing"),
    }
    container = CountingContainer(services)
    locator = ServiceLocator[Middleware](
        container, {"logging": (Middleware, "logging"), "tracing": (Middleware, "tracing")}
    )

    pairs: list[tuple[Hashable, Middleware]] = [pair async for pair in locator]

    assert [name for name, _ in pairs] == ["logging", "tracing"]
    assert [m.label for _, m in pairs] == ["logging", "tracing"]
    assert calls == ["logging", "tracing"]


async def test_an_unknown_name_is_a_lookup_error() -> None:
    with pytest.raises(UnknownLocatorKeyError) as caught:
        _ = await _locator([]).get("absent")

    assert caught.value.known == ("logging", "tracing")
    assert isinstance(caught.value, LookupError)


def test_service_locator_is_a_service_collection_interface() -> None:
    locator = _locator([])

    assert isinstance(locator, ServiceCollectionInterface)
    assert isinstance(locator, ServiceProviderInterface)


@final
class Greeter:
    label: str

    def __init__(self, label: str) -> None:
        self.label = label


def _greeters_factory(container: ContainerInterface) -> ServiceLocator[Greeter]:
    return ServiceLocator[Greeter](container, {"en": (Greeter, "en"), "fr": (Greeter, "fr")})


@final
@as_bundle("greeters")
class GreetersBundle(Bundle):
    @override
    def load_extension(
        self,
        config: object,
        services: ServiceConfigurator,
        builder: object,
    ) -> None:
        del config, builder
        _ = services.instance(Greeter("hello"), qualifier="en")
        _ = services.instance(Greeter("bonjour"), qualifier="fr")
        _ = services.set(_greeters_factory)


async def test_a_bundle_can_expose_a_service_locator_over_targeted_services() -> None:
    kernel = Kernel("json", resources=(), bundles={GreetersBundle: {"all": True}})
    compiled = kernel.build()

    locator = await compiled.container.get(ServiceLocator[Greeter])

    assert isinstance(locator, ServiceLocator)
    assert (await locator.get("en")).label == "hello"
    assert (await locator.get("fr")).label == "bonjour"
    pairs: list[tuple[Hashable, Greeter]] = [pair async for pair in locator]
    assert [name for name, _ in pairs] == ["en", "fr"]
