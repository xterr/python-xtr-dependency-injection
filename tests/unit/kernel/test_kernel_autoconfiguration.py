"""Nominal ``register_for_autoconfiguration`` + ``@autoconfigure``.

Covers the kernel's nominal ``instanceof``-style tagging via
``ContainerBuilder.register_for_autoconfiguration`` (used for ``kernel.reset``),
lifetime override, "explicit wins", the kernel-services carve-out,
``@autoconfigure`` / ``@autoconfigure_tag`` decorators, and end-to-end reset
through ``ResetInterface``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typing_extensions import override
from xtr_service_contracts import ResetInterface

from tests.fixtures.app_autoconfigure import Buffer, StructuralOnly
from tests.fixtures.app_autoconfigure_factory import ProductViaFactory
from tests.fixtures.app_autoconfigure_markers import (
    DefaultTagName,
    TaggedByAutoconfigure,
    TaggedWithCallable,
)
from xtr_dependency_injection.bundle import Bundle, as_bundle
from xtr_dependency_injection.exception import ConfigProviderError
from xtr_dependency_injection.exception._naming import qualified_name
from xtr_dependency_injection.kernel import Kernel
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.builder.container_builder import ContainerBuilder
    from xtr_dependency_injection.builder.service_configurator import ServiceConfigurator
    from xtr_dependency_injection.bundle.bundle import AnyBundle

pytestmark = pytest.mark.anyio


def _kernel(
    resources: tuple[str, ...] = ("tests.fixtures.app_autoconfigure",),
    *,
    bundles: Mapping[type[AnyBundle], Mapping[str, bool]] | None = None,  # type: ignore[misc]
) -> Kernel:
    return Kernel(
        "tests.fixtures.app_autoconfigure",
        env="dev",
        bundles=bundles or {},
        resources=resources,
    )


# --- kernel.reset via ResetInterface ---------------------------------------


async def test_a_reset_interface_service_is_reset_through_the_resetter() -> None:
    compiled = _kernel().build()
    buffer = await compiled.container.get(Buffer)
    buffer.items.extend(["a", "b"])

    await (await compiled.container.get(ServicesResetter)).reset()

    assert buffer.resets == 1
    assert buffer.items == []


async def test_a_structural_only_reset_class_is_not_autoconfigured() -> None:
    compiled = _kernel().build()
    structural = await compiled.container.get(StructuralOnly)

    await (await compiled.container.get(ServicesResetter)).reset()

    # ``StructuralOnly`` has ``reset()`` but is not a nominal subclass of
    # ``ResetInterface`` — the resetter must not track it.
    assert structural.resets == 0


async def test_kernel_services_are_not_autoconfigured() -> None:
    compiled = _kernel().build()

    resetter = await compiled.container.get(ServicesResetter)
    # ``ServicesResetter`` itself has ``reset()`` (async), but is kernel
    # origin: the ``kernel.reset`` autoconfigure must skip it, otherwise it
    # would self-track and loop.
    await resetter.reset()
    await resetter.reset()


# --- @autoconfigure / @autoconfigure_tag markers ---------------------------


async def test_autoconfigure_marker_adds_static_tags() -> None:
    compiled = _kernel(("tests.fixtures.app_autoconfigure_markers",)).build()

    reports = [d for d in compiled.report.definitions if d.key[0] is TaggedByAutoconfigure]

    assert len(reports) == 1
    assert "marker.static" in reports[0].tags


async def test_autoconfigure_marker_callable_tag_attributes_land_on_the_definition() -> None:
    compiled = _kernel(("tests.fixtures.app_autoconfigure_markers",)).build()

    reports = [d for d in compiled.report.definitions if d.key[0] is TaggedWithCallable]

    assert len(reports) == 1
    assert "marker.callable" in reports[0].tags


async def test_autoconfigure_tag_default_name_uses_qualified_name() -> None:
    compiled = _kernel(("tests.fixtures.app_autoconfigure_markers",)).build()

    reports = [d for d in compiled.report.definitions if d.key[0] is DefaultTagName]

    assert len(reports) == 1
    assert qualified_name(DefaultTagName) in reports[0].tags


# --- register_for_autoconfiguration from a bundle --------------------------


class Plugin:
    pass


class Alpha(Plugin):
    pass


class Beta(Plugin):
    pass


@as_bundle("probe")
class ProbeBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config
        _ = services.set(Alpha)
        _ = services.set(Beta)
        _ = builder.register_for_autoconfiguration(Plugin).add_tag("probe.plugin", role="mailer")


async def test_register_for_autoconfiguration_tags_every_matched_definition() -> None:
    compiled = _kernel(resources=(), bundles={ProbeBundle: {"all": True}}).build()

    tags_alpha = next(d.tags for d in compiled.report.definitions if d.key[0] is Alpha)
    tags_beta = next(d.tags for d in compiled.report.definitions if d.key[0] is Beta)

    assert "probe.plugin" in tags_alpha
    assert "probe.plugin" in tags_beta


class ScopedTarget:
    pass


@as_bundle("scoped_probe")
class ScopedProbeBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config
        # Register with default singleton lifetime.
        _ = services.set(ScopedTarget)
        rule = builder.register_for_autoconfiguration(ScopedTarget)
        rule.lifetime = "scoped"


async def test_register_for_autoconfiguration_overrides_the_lifetime() -> None:
    compiled = _kernel(resources=(), bundles={ScopedProbeBundle: {"all": True}}).build()

    (report,) = [d for d in compiled.report.definitions if d.key[0] is ScopedTarget]

    assert report.lifetime == "scoped"


# --- explicit wins ---------------------------------------------------------


class ExplicitOverridingReset(ResetInterface):
    def __init__(self) -> None:
        self.calls: list[str] = []

    @override
    def reset(self) -> None:
        self.calls.append("reset")

    def clear(self) -> None:
        self.calls.append("clear")


@as_bundle("explicit")
class ExplicitBundle(Bundle):
    @override
    def load_extension(
        self, config: object, services: ServiceConfigurator, builder: ContainerBuilder
    ) -> None:
        del config, builder
        _ = services.set(ExplicitOverridingReset).add_tag("kernel.reset", method="clear")


async def test_an_explicit_kernel_reset_wins_over_the_autoconfigure_rule() -> None:
    compiled = _kernel(resources=(), bundles={ExplicitBundle: {"all": True}}).build()

    service = await compiled.container.get(ExplicitOverridingReset)
    await (await compiled.container.get(ServicesResetter)).reset()

    # The explicit ``method="clear"`` tag was kept; the rule did NOT add a
    # second ``kernel.reset`` tag with ``method="reset"``.
    assert service.calls == ["clear"]


# --- @autoconfigure(factory=...) -------------------------------------------


async def test_autoconfigure_factory_replaces_the_class_definition() -> None:
    compiled = _kernel(("tests.fixtures.app_autoconfigure_factory",)).build()

    built = await compiled.container.get(ProductViaFactory)

    assert built.tag == "from-factory"


async def test_autoconfigure_factory_return_type_must_match_the_class() -> None:
    with pytest.raises(ConfigProviderError):
        _ = _kernel(("tests.fixtures.app_autoconfigure_bad_factory",)).build()
