"""Kernel-level: environment variables read when a service is built, parameters resolved."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import pytest
from typing_extensions import override

from tests.fixtures.app_env import (
    EVENTS,
    AsyncSession,
    Beacon,
    DsnReader,
    Greeting,
    Label,
    Lighthouse,
    MailBundle,
    MailConfig,
    Mailer,
    Pager,
    PortPager,
    PortReader,
    Relay,
    RelayBadge,
    Signature,
    SyncSession,
    TokenReader,
    VaultLoader,
)
from xtr_dependency_injection import (
    Autowire,
    Bundle,
    ContainerBagInterface,
    Injected,
    Kernel,
    ServicesResetter,
    as_bundle,
    bind_callable,
)
from xtr_dependency_injection.config.env_placeholder import EnvPlaceholder
from xtr_dependency_injection.exception import (
    EnvPlaceholderError,
    MissingEnvironmentVariableError,
    ServiceResolutionError,
)
from xtr_dependency_injection.runtime.wireup_container import WireupContainer

if TYPE_CHECKING:
    from xtr_dependency_injection import ContainerBuilder, ServiceConfigurator

pytestmark = pytest.mark.anyio

ENVIRON = {
    "MAIL_HOST": "smtp.acme",
    "MAIL_PORT": "2525",
    "MAIL_USER": "mailer",
    "MAIL_WORKERS": "4",
}


def _kernel(environ: dict[str, str], *resources: str) -> Kernel:
    return Kernel(
        "tests.fixtures.app_env",
        bundles={MailBundle: {"all": True}},
        resources=resources or ("tests.fixtures.app_env",),
        env="dev",
        environ=environ,
    )


def test_the_container_builds_without_the_environment_it_will_run_in() -> None:
    compiled = _kernel({}).build()

    (report,) = [config for config in compiled.report.configs if config.bundle == "mail"]
    assert repr(report.value).count("env(") >= 3
    assert "smtp.acme" not in compiled.report.render()


async def test_a_config_is_resolved_when_the_service_needing_it_is_built() -> None:
    async with await _kernel(ENVIRON).boot() as booted:
        mailer = await booted.container.get(Mailer)

    project_dir = str(Path.cwd())
    assert mailer.config.host == "smtp.acme"
    assert mailer.config.port == 2525
    assert type(mailer.config.port) is int
    assert mailer.config.user == "mailer"
    assert mailer.config.spool.endswith("/var/spool")
    assert mailer.config.spool.startswith(project_dir.split("/packages/", maxsplit=1)[0])
    assert mailer.config.literal == "100% sure"


async def test_a_missing_variable_fails_only_the_service_needing_it() -> None:
    async with await _kernel({"MAIL_PORT": "25"}).boot() as booted:
        reader = await booted.container.get(PortReader)
        with pytest.raises(ServiceResolutionError) as caught:
            _ = await booted.container.get(Mailer)

    assert reader.port == 25
    assert isinstance(caught.value.__cause__, MissingEnvironmentVariableError)


async def test_autowire_env_resolves_for_classes_factories_and_hooks() -> None:
    EVENTS.clear()
    async with await _kernel(ENVIRON).boot() as booted:
        reader = await booted.container.get(PortReader)
        label = await booted.container.get(Label)

    assert reader.port == 2525
    assert label.text == "port 2525"
    assert EVENTS == ["boot port 2525"]


async def test_a_parameter_holding_a_placeholder_is_resolved_when_injected() -> None:
    async with await _kernel(ENVIRON).boot() as booted:
        reader = await booted.container.get(DsnReader)
        container = booted.container
        assert isinstance(container, WireupContainer)
        with pytest.raises(EnvPlaceholderError, match=r"app\.dsn"):
            _ = container.get_parameter("app.dsn")
        raw = container.get_parameter_raw("app.workers")
        workers = await container.resolve_env_placeholders(raw)
        log_dir = container.get_parameter("app.log_dir")

    assert reader.dsn == "smtp://smtp.acme"
    assert isinstance(raw, EnvPlaceholder)
    assert workers == 4
    assert isinstance(log_dir, str)
    assert log_dir.endswith("/var/log")


async def test_loaders_and_processors_are_autoconfigured_and_reset() -> None:
    VaultLoader.loads = 0
    VaultLoader.values = {"VAULT_TOKEN": "t-1"}
    async with await _kernel(ENVIRON).boot() as booted:
        first = await booted.container.get(TokenReader)
        await (await booted.container.get(ServicesResetter)).reset()
        VaultLoader.values = {"VAULT_TOKEN": "t-2"}
        container = booted.container
        assert isinstance(container, WireupContainer)
        rotated = await container.get_env("VAULT_TOKEN")

    assert (first.token, first.shout) == ("t-1", "SMTP.ACME")
    assert rotated == "t-2"
    assert VaultLoader.loads == 2


async def test_a_bound_callable_reads_the_environment_per_call() -> None:
    async def handler(port: Annotated[int, Autowire(env="int:MAIL_PORT")]) -> int:
        return port

    environ = dict(ENVIRON)
    async with await _kernel(environ).boot() as booted:
        bound = bind_callable(booted.container, handler)
        first = await bound()
        environ["MAIL_PORT"] = "2600"
        second = await bound()

    assert (first, second) == (2525, 2600)


async def test_a_bundle_factory_closing_over_its_config_reads_the_environment() -> None:
    async with await _kernel(ENVIRON).boot() as booted:
        greeting = await booted.container.get(Greeting)
        signature = await booted.container.get(Signature)

    assert greeting.text == "hello smtp.acme:2525"
    assert signature.host == "smtp.acme"


async def test_definition_arguments_are_resolved_when_the_service_is_built() -> None:
    compiled = _kernel(ENVIRON).build()
    (report,) = [d for d in compiled.report.definitions if d.key == (Relay, None)]
    async with await compiled.boot() as booted:
        relay = await booted.container.get(Relay)

    assert "host=env(MAIL_HOST)" in report.arguments
    assert isinstance(relay, RelayBadge)
    assert relay.label == "smtp.acme"
    assert (relay.inner.host, relay.inner.port) == ("smtp.acme", 2525)
    assert type(relay.inner.port) is int
    assert relay.inner.spool.endswith("/relay")
    assert "%" not in relay.inner.spool


async def test_a_null_decorators_arguments_are_resolved() -> None:
    async with await _kernel(ENVIRON).boot() as booted:
        beacon = await booted.container.get(Lighthouse)

    assert isinstance(beacon, Beacon)
    assert (beacon.inner, beacon.label) == (None, "smtp.acme")


async def test_a_null_decorator_of_a_missing_service_reads_the_environment() -> None:
    async with await _kernel(ENVIRON).boot() as booted:
        pager = await booted.container.get(Pager)

    assert isinstance(pager, PortPager)
    assert pager.inner is None
    assert pager.port == 2525
    assert type(pager.port) is int


async def test_a_generator_factory_reading_the_environment_is_closed_with_its_scope() -> None:
    async def handler(a: Injected[AsyncSession], s: Injected[SyncSession]) -> None:
        del a, s

    async with await _kernel(ENVIRON).boot() as booted:
        EVENTS.clear()
        _ = await bind_callable(booted.container, handler, per_call_scope=True)()

    assert sorted(EVENTS) == ["async 2525 closed", "sync 2525 closed"]


async def test_a_generator_factory_reading_the_environment_sees_its_scope_fail() -> None:
    async def handler(a: Injected[AsyncSession], s: Injected[SyncSession]) -> None:
        del a, s
        msg = "boom"
        raise RuntimeError(msg)

    async with await _kernel(ENVIRON).boot() as booted:
        EVENTS.clear()
        with pytest.raises(RuntimeError, match="boom"):
            _ = await bind_callable(booted.container, handler, per_call_scope=True)()

    assert sorted(EVENTS) == ["async 2525 saw boom", "sync 2525 saw boom"]


async def test_the_container_bag_exposes_the_resolved_parameters() -> None:
    async with await _kernel(ENVIRON).boot() as booted:
        bag = await booted.container.get(ContainerBagInterface)

    assert bag.has("kernel.name")
    assert bag.get("kernel.environment") == "dev"
    assert "app" in bag.all()
    assert bag.resolve_value("%kernel.name%!") == "app_env!"


def test_kernel_environ_selects_the_environment_and_debug() -> None:
    kernel = Kernel("tests.fixtures.app_env", environ={"APP_ENV": "prod", "APP_DEBUG": "1"})

    assert kernel.environment == "prod"
    assert kernel.debug is True
    assert kernel.with_env("test").debug is True


def test_an_unknown_prefix_fails_the_build() -> None:
    with pytest.raises(EnvPlaceholderError, match="unsupported env var prefix 'itn'"):
        _ = _kernel(ENVIRON, "tests.fixtures.app_env_invalid").build()


def test_a_json_placeholder_cannot_be_embedded_in_a_string() -> None:
    with pytest.raises(EnvPlaceholderError, match="embedded in a string"):
        _ = _kernel(ENVIRON, "tests.fixtures.app_env_embedded").build()


@as_bundle("structural", config=MailConfig)
class StructuralBundle(Bundle[MailConfig]):
    @override
    def load_extension(
        self, config: MailConfig, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del services, builder
        if config.port:  # the port is a placeholder: it cannot decide what gets registered
            return


def test_a_placeholder_cannot_decide_structure() -> None:
    kernel = Kernel(
        "tests.fixtures.app_env",
        bundles={StructuralBundle: {"all": True}},
        resources=("tests.fixtures.app_env",),
        environ=ENVIRON,
    )

    with pytest.raises(EnvPlaceholderError, match="cannot decide"):
        _ = kernel.build()
