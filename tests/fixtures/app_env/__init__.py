"""Fixture app: configs, parameters and services reading the environment lazily."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Annotated, ClassVar

from typing_extensions import override

from xtr_dependency_injection import (
    Autowire,
    AutowireDecorated,
    Bundle,
    ContainerBuilder,
    EnvVarLoaderInterface,
    EnvVarProcessorInterface,
    OnInvalid,
    ServiceConfigurator,
    as_bundle,
    as_decorator,
    as_service,
    configure,
    env,
    on_boot,
    parameters,
)

EVENTS: list[str] = []


@dataclass(frozen=True)
class MailConfig:
    host: str = "localhost"
    port: int = 25
    spool: str = "%kernel.project_dir%/var/spool"
    user: str = "%env(MAIL_USER)%"
    literal: str = "100%% sure"


class Mailer:
    def __init__(self, config: MailConfig) -> None:
        self.config: MailConfig = config


class PortReader:
    def __init__(self, port: Annotated[int, Autowire(env="int:MAIL_PORT")]) -> None:
        self.port: int = port


class Label:
    def __init__(self, text: str) -> None:
        self.text: str = text


def port_label(port: Annotated[int, Autowire(env="int:MAIL_PORT")]) -> Label:
    return Label(f"port {port}")


class Greeting:
    def __init__(self, text: str) -> None:
        self.text: str = text


class Signature:
    def __init__(self, host: str) -> None:
        self.host: str = host


class Relay:
    def __init__(self, host: str, port: int, spool: str) -> None:
        self.host: str = host
        self.port: int = port
        self.spool: str = spool


class RelayBadge(Relay):
    def __init__(self, inner: Annotated[Relay, AutowireDecorated()], label: str) -> None:
        super().__init__(inner.host, inner.port, inner.spool)
        self.inner: Relay = inner
        self.label: str = label


class Lighthouse:
    pass


class Beacon(Lighthouse):
    def __init__(
        self, inner: Annotated[Lighthouse | None, AutowireDecorated()], label: str
    ) -> None:
        self.inner: Lighthouse | None = inner
        self.label: str = label


class DsnReader:
    def __init__(self, dsn: Annotated[str, Autowire(param="app.dsn")]) -> None:
        self.dsn: str = dsn


@as_bundle("mail", config=MailConfig)
class MailBundle(Bundle[MailConfig]):
    @override
    def load_extension(
        self, config: MailConfig, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del builder

        def greeting() -> Greeting:
            return Greeting(f"hello {config.host}:{config.port}")

        def signature(*, host: str = config.host) -> Signature:
            return Signature(host)

        _ = services.set(greeting)
        _ = services.set(signature)
        _ = (
            services.set(Relay)
            .set_argument("host", config.host)
            .set_argument("port", config.port)
            .set_argument("spool", "%kernel.project_dir%/relay")
        )
        _ = services.set(RelayBadge).set_decorated_service(Relay).set_argument("label", config.host)
        _ = (
            services.set(Beacon)
            .set_decorated_service(Lighthouse, on_invalid=OnInvalid.NULL)
            .set_argument("label", config.host)
        )
        _ = services.set(Mailer)
        _ = services.set(PortReader)
        _ = services.set(port_label)
        _ = services.set(DsnReader)


@configure
def mail(config: MailConfig) -> MailConfig:
    return replace(config, host=env("MAIL_HOST"), port=env("MAIL_PORT", int, default=25))


@parameters
def app_parameters() -> dict[str, object]:
    return {
        "app": {
            "dsn": f"smtp://{env('MAIL_HOST')}",
            "log_dir": "%kernel.project_dir%/var/log",
            "workers": "%env(int:MAIL_WORKERS)%",
        }
    }


@as_service
class VaultLoader(EnvVarLoaderInterface):
    loads: ClassVar[int] = 0
    values: ClassVar[dict[str, str]] = {"VAULT_TOKEN": "t-1"}

    @override
    def load_env_vars(self) -> Mapping[str, str]:
        type(self).loads += 1
        return dict(type(self).values)


@as_service
class UpperProcessor(EnvVarProcessorInterface):
    @override
    def get_env(self, prefix: str, name: str, get_env: Callable[[str], object]) -> object:
        return str(get_env(name)).upper()

    @override
    @classmethod
    def get_provided_types(cls) -> Mapping[str, str]:
        return {"upper": "string"}


@as_service
class TokenReader:
    def __init__(
        self,
        token: Annotated[str, Autowire(env="VAULT_TOKEN")],
        shout: Annotated[str, Autowire(env="upper:MAIL_HOST")],
    ) -> None:
        self.token: str = token
        self.shout: str = shout


@on_boot
async def record_port(port: Annotated[int, Autowire(env="int:MAIL_PORT")]) -> None:
    EVENTS.append(f"boot port {port}")


class SyncSession:
    pass


class AsyncSession:
    pass


@as_service(lifetime="scoped")
def sync_session(port: Annotated[int, Autowire(env="int:MAIL_PORT")]) -> Iterator[SyncSession]:
    try:
        yield SyncSession()
    except RuntimeError as error:
        EVENTS.append(f"sync {port} saw {error}")
        raise
    EVENTS.append(f"sync {port} closed")


@as_service(lifetime="scoped")
async def async_session(
    port: Annotated[int, Autowire(env="int:MAIL_PORT")],
) -> AsyncIterator[AsyncSession]:
    try:
        yield AsyncSession()
    except RuntimeError as error:
        EVENTS.append(f"async {port} saw {error}")
        raise
    EVENTS.append(f"async {port} closed")


class Pager:
    pass


@as_decorator(Pager, on_invalid=OnInvalid.NULL)
class PortPager(Pager):
    def __init__(
        self,
        inner: Annotated[Pager | None, AutowireDecorated()],
        port: Annotated[int, Autowire(env="int:MAIL_PORT")],
    ) -> None:
        self.inner: Pager | None = inner
        self.port: int = port
