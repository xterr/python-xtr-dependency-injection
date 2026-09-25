"""The whole kernel over two installed distributions and an application nobody lists bundles in.

``alpha`` requires ``beta`` and orders itself after ``gamma``, which is not
installed. The application configures ``alpha`` (a base provider and a
``prod``-only transform), overrides ``beta``'s mailer, decorates ``alpha``'s
greeter, adds a compiler pass, and hooks boot and shutdown.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Protocol, cast

import pytest

from xtr_dependency_injection import Kernel, KernelInterface
from xtr_dependency_injection.builder import Origin

if TYPE_CHECKING:
    from tests.support.fake_dist import FakeDistributions
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
    def load(self, config, services) -> None:
        services.service(SmtpMailer, as_type=Mailer)

    async def boot(self, container) -> None:
        EVENTS.append("boot:beta")

    async def shutdown(self, container) -> None:
        EVENTS.append("shutdown:beta")
"""

ALPHA = """
from dataclasses import dataclass

from acme_beta import EVENTS, Mailer
from xtr_dependency_injection import Bundle, as_bundle


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


@as_bundle("alpha", config=AlphaConfig, requires=("beta",), optional=("gamma",))
class AlphaBundle(Bundle[AlphaConfig]):
    def load(self, config, services) -> None:
        services.factory(greeter)

    async def boot(self, container) -> None:
        EVENTS.append("boot:alpha")

    async def shutdown(self, container) -> None:
        EVENTS.append("shutdown:alpha")
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
from wireup import injectable

from acme_alpha import Greeter
from acme_beta import Mailer
from xtr_dependency_injection import ContainerBuilder, Inner, as_decorator, compiler_pass


@injectable(as_type=Mailer)
class FakeMailer(Mailer):
    def send(self) -> str:
        return "fake"


@as_decorator(Greeter)
class ShoutingGreeter(Greeter):
    def __init__(self, inner: Inner[Greeter]) -> None:
        self.inner = inner

    def greet(self) -> str:
        return self.inner.greet().upper()


class Note:
    def __init__(self, text: str) -> None:
        self.text = text


@compiler_pass
def note_the_mailer(builder: ContainerBuilder) -> None:
    (mailer,) = builder.definitions(Mailer)
    builder.instance(Note(f"mailer from {mailer.origin.kind}"))
"""

APP_HOOKS = """
from wireup import Injected

from acme_alpha import Greeter
from acme_beta import EVENTS
from xtr_dependency_injection import on_boot, on_shutdown


@on_boot
async def greet(greeter: Injected[Greeter]) -> None:
    EVENTS.append(f"boot:app {greeter.greet()}")


@on_shutdown
def goodbye() -> None:
    EVENTS.append("shutdown:app")
"""


@pytest.fixture
def compiled(fake_dist: FakeDistributions) -> CompiledKernel:
    fake_dist.install("acme-beta", {"beta": "acme_beta:BetaBundle"}, {"acme_beta": BETA})
    fake_dist.install("acme-alpha", {"alpha": "acme_alpha:AlphaBundle"}, {"acme_alpha": ALPHA})
    fake_dist.add_modules(
        {
            "acme_app.config": APP_CONFIG,
            "acme_app.services": APP_SERVICES,
            "acme_app.hooks": APP_HOOKS,
        }
    )
    return Kernel("acme_app", env="prod").build()


def test_the_bundle_report_shows_every_bundle_discovered_and_ordered(
    compiled: CompiledKernel,
) -> None:
    rows = [
        (report.name, report.source, report.state, report.requires, report.optional)
        for report in compiled.report.bundles
    ]

    assert rows == [
        ("kernel", "explicit", "active", (), ()),
        ("beta", "discovered", "active", (), ()),
        ("alpha", "discovered", "active", ("beta",), ("gamma",)),
    ]


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

    assert mailer.origin == Origin("app", "acme_app.services:FakeMailer")
    assert mailer.overrides == (Origin("bundle", "beta"),)
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
