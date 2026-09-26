"""The whole kernel over an application that lists two bundles.

``alpha`` requires ``beta`` (via ``@required_bundle(BetaBundle)``) and marks
``gamma`` as an optional string target (``@required_bundle("...", ignore_on_invalid=True)``)
whose module is never installed, exercising the ``ignore_on_invalid`` path.
The application configures ``alpha`` (a base provider and a ``prod``-only
transform), overrides ``beta``'s mailer, decorates ``alpha``'s greeter, adds a
compiler pass, and hooks boot and shutdown.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Protocol, cast

import pytest

from xtr_dependency_injection import Kernel, KernelInterface
from xtr_dependency_injection.builder import Origin

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules
    from xtr_dependency_injection import CompiledKernel

pytestmark = pytest.mark.anyio


class Greets(Protocol):
    def greet(self) -> str: ...


BETA = """
from xtr_dependency_injection import Bundle, as_bundle

EVENTS: list[str] = []


class Mailer:
    def send(self) -> str:
        return "smtp"


class SmtpMailer(Mailer):
    pass


@as_bundle("beta")
class BetaBundle(Bundle):
    def load_extension(self, config, services, builder) -> None:
        _ = services.set(SmtpMailer)
        services.alias(Mailer, SmtpMailer)

    async def boot(self) -> None:
        EVENTS.append("boot:beta")

    async def shutdown(self) -> None:
        EVENTS.append("shutdown:beta")
"""

ALPHA = """
from dataclasses import dataclass

from acme_beta import EVENTS, BetaBundle, Mailer
from xtr_dependency_injection import Bundle, as_bundle, required_bundle


@dataclass(frozen=True)
class AlphaConfig:
    greeting: str = "hello"


class Greeter:
    def __init__(self, config: AlphaConfig, mailer: Mailer) -> None:
        self.config = config
        self.mailer = mailer

    def greet(self) -> str:
        return f"{self.config.greeting} via {self.mailer.send()}"


def greeter(config: AlphaConfig, mailer: Mailer) -> Greeter:
    return Greeter(config, mailer)


@required_bundle("gamma_not_installed:GammaBundle", ignore_on_invalid=True)
@required_bundle(BetaBundle)
@as_bundle("alpha", config=AlphaConfig)
class AlphaBundle(Bundle[AlphaConfig]):
    def load_extension(self, config, services, builder) -> None:
        _ = services.set(greeter)

    async def boot(self) -> None:
        EVENTS.append("boot:alpha")

    async def shutdown(self) -> None:
        EVENTS.append("shutdown:alpha")
"""

APP_BUNDLES = """
from acme_alpha import AlphaBundle

BUNDLES = {AlphaBundle: {"all": True}}
"""

APP_CONFIG = """
from dataclasses import replace

from acme_alpha import AlphaConfig
from xtr_dependency_injection import configure, when


@configure
def alpha() -> AlphaConfig:
    return AlphaConfig(greeting="hi")


@configure
@when("prod")
def alpha_prod(config: AlphaConfig) -> AlphaConfig:
    return replace(config, greeting=config.greeting + " from prod")
"""

APP_SERVICES = """
from typing import Annotated

from acme_alpha import Greeter
from acme_beta import Mailer
from xtr_dependency_injection import (
    AutowireDecorated,
    ContainerBuilder,
    as_decorator,
    as_service,
    compiler_pass,
)
from xtr_dependency_injection.builder import Definition, Origin


class FakeMailer(Mailer):
    def send(self) -> str:
        return "fake"


@as_service()
def fake_mailer() -> Mailer:
    return FakeMailer()


@as_decorator(Greeter)
class ShoutingGreeter(Greeter):
    def __init__(self, inner: Annotated[Greeter, AutowireDecorated()]) -> None:
        self.inner = inner

    def greet(self) -> str:
        return self.inner.greet().upper()


class Note:
    def __init__(self, text: str) -> None:
        self.text = text


@compiler_pass
class NoteTheMailer:
    def process(self, builder: ContainerBuilder) -> None:
        (mailer,) = [d for d in builder.get_definitions() if d.key[0] is Mailer]
        note = Note(f"mailer from {mailer.origin.kind}")
        _ = builder.set_definition(
            Definition(
                key=(Note, None),
                provider=note,
                kind="instance",
                lifetime="singleton",
                origin=Origin("app", "acme_app.services:NoteTheMailer"),
            )
        )
"""

APP_HOOKS = """
from acme_alpha import Greeter
from acme_beta import EVENTS
from xtr_dependency_injection import Injected, on_boot, on_shutdown


@on_boot
async def greet(greeter: Injected[Greeter]) -> None:
    EVENTS.append(f"boot:app {greeter.greet()}")


@on_shutdown
def goodbye() -> None:
    EVENTS.append("shutdown:app")
"""


@pytest.fixture
def compiled(scratch_modules: ScratchModules) -> CompiledKernel:
    scratch_modules.write(
        {
            "acme_beta": BETA,
            "acme_alpha": ALPHA,
            "acme_app.bundles": APP_BUNDLES,
            "acme_app.config": APP_CONFIG,
            "acme_app.services": APP_SERVICES,
            "acme_app.hooks": APP_HOOKS,
        }
    )
    return Kernel("acme_app", env="prod").build()


def test_the_bundle_report_shows_every_bundle_activated_and_ordered(
    compiled: CompiledKernel,
) -> None:
    rows = [
        (report.name, report.source, report.state, report.required)
        for report in compiled.report.bundles
        if report.state == "active"
    ]

    assert rows == [
        ("kernel", "kernel", "active", ()),
        ("beta", "required", "active", ()),
        ("alpha", "listed", "active", ("beta",)),
    ]


def test_an_ignore_on_invalid_target_is_reported_as_skipped(
    compiled: CompiledKernel,
) -> None:
    skipped = [
        report
        for report in compiled.report.bundles
        if report.qualname == "gamma_not_installed:GammaBundle"
    ]

    assert len(skipped) == 1
    assert skipped[0].state == "skipped"


def test_the_config_is_resolved_with_its_provenance(compiled: CompiledKernel) -> None:
    (alpha,) = [config for config in compiled.report.configs if config.bundle == "alpha"]

    assert repr(alpha.value) == "AlphaConfig(greeting='hi from prod')"
    assert alpha.steps == (
        "default",
        "base acme_app.config:alpha",
        "transform acme_app.config:alpha_prod",
    )


async def test_the_application_overrides_the_bundles_service(compiled: CompiledKernel) -> None:
    (mailer,) = [d for d in compiled.report.definitions if d.key[0].__name__ == "Mailer"]

    assert mailer.origin == Origin("app", "acme_app.services:fake_mailer")
    note = [d for d in compiled.report.definitions if d.key[0].__name__ == "Note"]
    assert len(note) == 1


async def test_the_decorator_wraps_the_bundles_service(compiled: CompiledKernel) -> None:
    (greeter,) = [d for d in compiled.report.definitions if d.key[0].__name__ == "Greeter"]
    info = await compiled.container.get(KernelInterface)

    assert greeter.decorated_by == ("acme_app.services:ShoutingGreeter",)
    assert info.bundles == ("kernel", "beta", "alpha")
    greeting = cast("Greets", await compiled.container.get(greeter.key[0]))
    assert greeting.greet() == "HI FROM PROD VIA FAKE"


async def test_boot_and_shutdown_run_bundles_then_app_and_back(compiled: CompiledKernel) -> None:
    # Installed by the fixture, so only importable now.
    events = cast("list[str]", vars(importlib.import_module("acme_beta"))["EVENTS"])

    booted = await compiled.boot()
    await booted.shutdown()

    assert events == [
        "boot:beta",
        "boot:alpha",
        "boot:app HI FROM PROD VIA FAKE",
        "shutdown:app",
        "shutdown:alpha",
        "shutdown:beta",
    ]
