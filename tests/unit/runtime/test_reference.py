from __future__ import annotations

from typing import final

import pytest
from typing_extensions import override

from xtr_dependency_injection import (
    Bundle,
    ContainerBuilder,
    Kernel,
    NoConfig,
    Reference,
    ServiceConfigurator,
    as_bundle,
)

pytestmark = pytest.mark.anyio


@final
class Client:
    def __init__(self, name: str) -> None:
        self.name = name


@final
@as_bundle("reference_fixture")
class _ClientsBundle(Bundle[NoConfig]):
    @override
    def load_extension(
        self,
        config: NoConfig,
        services: ServiceConfigurator,
        builder: ContainerBuilder,
    ) -> None:
        del config, builder
        _ = services.instance(Client("default"))
        _ = services.instance(Client("reports"), qualifier="reports")


def _kernel() -> Kernel:
    return Kernel(__name__, env="test", bundles={_ClientsBundle: {"all": True}}, resources=())


async def test_a_reference_resolves_to_the_service_it_names() -> None:
    async with await _kernel().boot() as booted:
        container = booted.container
        reports = await Reference(Client, "reports").resolve(container)
        default = await Reference(Client).resolve(container)

    assert isinstance(reports, Client)
    assert reports.name == "reports"
    assert isinstance(default, Client)
    assert default.name == "default"


async def test_it_tells_whether_the_container_provides_the_service() -> None:
    async with await _kernel().boot() as booted:
        assert Reference(Client, "reports").exists_in(booted.container)
        assert not Reference(Client, "absent").exists_in(booted.container)


def test_it_names_the_service_as_an_error_would() -> None:
    assert str(Reference(Client, "reports")) == "Client['reports']"
    assert str(Reference(Client)) == "Client"


def test_it_is_a_value() -> None:
    assert Reference(Client, "a") == Reference(Client, "a")
    assert hash(Reference(Client, "a")) == hash(Reference(Client, "a"))
