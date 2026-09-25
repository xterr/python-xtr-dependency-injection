"""S3: ``Sequence[T]`` and ``Mapping[Hashable, T]`` follow the order of ``injectables``."""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

import pytest
import wireup

from xtr_dependency_injection.compiler.registration import _clone_function

pytestmark = pytest.mark.anyio


class Plugin:
    name: str = "base"


@wireup.injectable(as_type=Plugin, qualifier="declared")
class DeclaredPlugin(Plugin):
    name: str = "declared"


class FactoryPlugin(Plugin):
    name: str = "factory"


class InstancePlugin(Plugin):
    name: str = "instance"


def factory_plugin() -> FactoryPlugin:
    return FactoryPlugin()


def _injectables() -> dict[str, object]:
    return {
        "declared": DeclaredPlugin,
        "factory": wireup.injectable(
            _clone_function(factory_plugin), as_type=Plugin, qualifier="factory"
        ),
        "instance": wireup.instance(InstancePlugin(), as_type=Plugin, qualifier="instance"),
    }


@pytest.mark.parametrize(
    "order",
    [("declared", "factory", "instance"), ("instance", "declared", "factory")],
)
async def test_sequence_follows_the_injectables_order(order: tuple[str, ...]) -> None:
    available = _injectables()
    container = wireup.create_async_container(injectables=[available[name] for name in order])

    plugins = await container.get(Sequence[Plugin])

    assert tuple(plugin.name for plugin in plugins) == order


@pytest.mark.parametrize(
    "order",
    [("factory", "instance", "declared"), ("declared", "instance", "factory")],
)
async def test_mapping_follows_the_injectables_order(order: tuple[str, ...]) -> None:
    available = _injectables()
    container = wireup.create_async_container(injectables=[available[name] for name in order])

    plugins = await container.get(Mapping[Hashable, Plugin])

    assert tuple(plugins) == order
