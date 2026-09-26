from __future__ import annotations

from typing import final

import pytest
from typing_extensions import override

from xtr_dependency_injection import (
    Bundle,
    ContainerBuilder,
    Kernel,
    NoConfig,
    ServiceConfigurator,
    as_bundle,
    optional_service,
)

pytestmark = pytest.mark.anyio


@final
class Channel:
    pass


@final
@as_bundle("optional_service_fixture")
class _ChannelBundle(Bundle[NoConfig]):
    @override
    def load_extension(
        self,
        config: NoConfig,
        services: ServiceConfigurator,
        builder: ContainerBuilder,
    ) -> None:
        del config, builder
        _ = services.instance(Channel(), qualifier="cache")


async def test_it_returns_the_service_when_provided_and_none_otherwise() -> None:
    kernel = Kernel(__name__, env="test", bundles={_ChannelBundle: {"all": True}}, resources=())

    async with await kernel.boot() as booted:
        provided = await optional_service(booted.container, Channel, "cache")
        missing = await optional_service(booted.container, Channel, "lock")

    assert isinstance(provided, Channel)
    assert missing is None
