"""Bundles for kernel tests: small, but each exercising one hook the kernel drives."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from typing_extensions import override

from xtr_dependency_injection.bundle import Bundle, as_bundle

if TYPE_CHECKING:
    from wireup import AsyncContainer

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator
    from xtr_dependency_injection.config.config_prepender import ConfigPrepender

EVENTS: list[str] = []


@dataclass(frozen=True)
class EchoConfig:
    greeting: str = "hello"
    channels: tuple[str, ...] = ()


class Echo:
    def __init__(self, config: EchoConfig) -> None:
        self.config: EchoConfig = config
        self.resets: int = 0

    def say(self) -> str:
        return self.config.greeting

    def reset(self) -> None:
        self.resets += 1


class Plugin:
    pass


def echo(config: EchoConfig) -> Echo:
    return Echo(config)


def tags_of(obj: object) -> tuple[str, ...]:
    tags: object = vars(obj).get("__echo_tags__", ()) if isinstance(obj, type) else ()
    return tags if isinstance(tags, tuple) else ()  # pyright: ignore[reportUnknownVariableType]


def register_tagged(obj: object, tag: str, services: ServiceConfigurator) -> None:
    if isinstance(obj, type):
        services.service(obj, as_type=Plugin, qualifier=tag)


@as_bundle("echo", config=EchoConfig)
class EchoBundle(Bundle[EchoConfig]):
    @override
    def load(self, config: EchoConfig, services: ServiceConfigurator) -> None:
        services.factory(echo)
        services.resettable(Echo)
        services.parameters({"echo": {"greeting": config.greeting}})
        services.autoconfigure(tags_of, register_tagged)

    @override
    async def boot(self, container: AsyncContainer) -> None:
        EVENTS.append("boot:echo")

    @override
    async def shutdown(self, container: AsyncContainer) -> None:
        EVENTS.append("shutdown:echo")


@as_bundle("chorus", requires=("echo",))
class ChorusBundle(Bundle):
    @override
    def prepend(self, configs: ConfigPrepender) -> None:
        configs.transform(EchoConfig, lambda c: replace(c, channels=(*c.channels, "chorus")))

    @override
    def load(self, config: object, services: ServiceConfigurator) -> None:
        services.scan("tests.fixtures.app_kernel_late")

    @override
    def process(self, builder: ContainerBuilder) -> None:
        EVENTS.append(f"process:chorus has echo={builder.has(Echo)}")

    @override
    async def boot(self, container: AsyncContainer) -> None:
        EVENTS.append("boot:chorus")

    @override
    async def shutdown(self, container: AsyncContainer) -> None:
        EVENTS.append("shutdown:chorus")


@as_bundle("failing")
class FailingBootBundle(Bundle):
    @override
    async def boot(self, container: AsyncContainer) -> None:
        raise RuntimeError("boot failed")

    @override
    async def shutdown(self, container: AsyncContainer) -> None:
        EVENTS.append("shutdown:failing")


@as_bundle("dev_only", envs=("dev",))
class DevOnlyBundle(Bundle):
    pass
