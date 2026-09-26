from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from wireup import Injected  # noqa: TC002 — main's annotations are read at runtime.

from tests.fixtures.app_kernel.processing import Marker
from tests.fixtures.app_kernel.services import DevOnly, Greeter
from tests.fixtures.app_with_bundles import ListedBundle
from tests.support.bundles import (
    EVENTS,
    ChorusBundle,
    DevOnlyBundle,
    Echo,
    EchoBundle,
    EchoConfig,
    FailingBootBundle,
    Plugin,
)
from xtr_dependency_injection.exception import (
    DuplicateServiceError,
    InvalidEnvironmentError,
    KernelAlreadyBootedError,
)
from xtr_dependency_injection.kernel import Kernel, KernelInterface
from xtr_dependency_injection.runtime.services_resetter import ServicesResetter

if TYPE_CHECKING:
    from collections.abc import Mapping

    from xtr_dependency_injection.bundle.bundle import AnyBundle

pytestmark = pytest.mark.anyio

APP = "tests.fixtures.app_kernel"

_DEFAULT_BUNDLES: dict[type[AnyBundle], Mapping[str, bool]] = {  # type: ignore[misc]
    EchoBundle: {"all": True},
    ChorusBundle: {"all": True},
}


@pytest.fixture(autouse=True)
def _clear_events() -> None:
    EVENTS.clear()


def _kernel(
    env: str = "dev",
    *,
    bundles: Mapping[type[AnyBundle], Mapping[str, bool]] | None = None,  # type: ignore[misc]
    name: str | None = None,
    allowed_envs: tuple[str, ...] | None = None,
) -> Kernel:
    return Kernel(
        APP,
        env=env,
        name=name,
        bundles=bundles if bundles is not None else _DEFAULT_BUNDLES,
        allowed_envs=allowed_envs,
    )


def test_constructing_a_kernel_does_no_work() -> None:
    kernel = Kernel("an.app.that.does.not.exist", env="dev")

    assert kernel.name == "exist"


def test_the_environment_defaults_to_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")

    assert Kernel(APP).environment == "staging"


def test_the_environment_defaults_to_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)

    assert Kernel(APP).environment == "dev"


def test_debug_defaults_to_on_outside_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_DEBUG", raising=False)

    assert Kernel(APP, env="dev").debug
    assert not Kernel(APP, env="prod").debug


def test_debug_reads_app_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DEBUG", "0")

    assert not Kernel(APP, env="dev").debug


def test_an_explicit_name_wins() -> None:
    assert Kernel(APP, name="shop").name == "shop"


def test_the_project_dir_is_the_nearest_pyproject() -> None:
    assert Kernel(APP).project_dir == Path(__file__).resolve().parents[3]


def test_with_env_keeps_the_recipe_for_another_environment() -> None:
    kernel = _kernel(name="shop").with_env("prod", debug=True)

    assert (kernel.name, kernel.environment, kernel.debug) == ("shop", "prod", True)


def test_a_disallowed_environment_is_refused() -> None:
    with pytest.raises(InvalidEnvironmentError):
        _ = _kernel(env="qa", allowed_envs=("dev", "prod")).build()


async def test_the_built_container_provides_the_app_and_bundle_services() -> None:
    compiled = _kernel().build()

    greeter = await compiled.container.get(Greeter)

    assert greeter.greet() == "please, HELLO!"


async def test_a_bundle_config_is_injectable_and_resolved_in_order() -> None:
    compiled = _kernel(env="prod").build()

    config = await compiled.container.get(EchoConfig)

    assert config == EchoConfig(greeting="HELLO prod", channels=("chorus",))


async def test_the_kernel_is_a_service() -> None:
    compiled = _kernel(name="shop").build()

    info = await compiled.container.get(KernelInterface)

    assert (info.name, info.environment, info.bundles) == (
        "shop",
        "dev",
        ("kernel", "echo", "chorus"),
    )
    assert info.report is compiled.report
    assert isinstance(info, KernelInterface)


async def test_kernel_parameters_are_injectable() -> None:
    compiled = _kernel(name="shop").build()

    assert compiled.container.get_parameter("kernel.name") == "shop"
    assert compiled.container.get_parameter("kernel.environment") == "dev"
    assert compiled.container.get_parameter("echo.greeting") == "HELLO"


async def test_an_env_excluded_object_is_not_collected() -> None:
    compiled = _kernel(env="prod").build()

    assert ("tests.fixtures.app_kernel.services:DevOnly", "@when(dev) excludes 'prod'") in (
        compiled.report.scan.skipped
    )
    assert DevOnly.__name__ not in compiled.report.render("definitions")


async def test_autoconfigure_registers_tagged_candidates() -> None:
    compiled = _kernel().build()

    alpha = await compiled.container.get(Plugin, "alpha")

    assert type(alpha).__name__ == "TaggedPlugin"


async def test_a_late_scan_registers_its_marked_services() -> None:
    compiled = _kernel().build()

    assert "tests.fixtures.app_kernel_late" in compiled.report.scan.modules


async def test_compiler_passes_see_every_definition() -> None:
    compiled = _kernel().build()

    marker = await compiled.container.get(Marker)

    assert marker.text == "echo defined: True"
    assert "process:chorus has echo=True" in EVENTS


async def test_a_resettable_service_is_reset_through_the_resetter() -> None:
    compiled = _kernel().build()
    echo = await compiled.container.get(Echo)
    inner = getattr(echo, "inner", echo)

    await (await compiled.container.get(ServicesResetter)).reset()

    assert isinstance(inner, Echo)
    assert inner.resets == 1


async def test_boot_and_shutdown_run_in_order() -> None:
    booted = await _kernel().boot()

    await booted.shutdown()

    assert EVENTS[1:] == [
        "boot:echo",
        "boot:chorus",
        "boot:app first",
        "boot:app please, HELLO!",
        "shutdown:app",
        "shutdown:chorus",
        "shutdown:echo",
    ]


async def test_shutdown_is_idempotent() -> None:
    booted = await _kernel().boot()
    await booted.shutdown()
    EVENTS.clear()

    await booted.shutdown()

    assert EVENTS == []


async def test_a_compiled_kernel_boots_once() -> None:
    compiled = _kernel().build()
    booted = await compiled.boot()

    with pytest.raises(KernelAlreadyBootedError):
        _ = await compiled.boot()
    await booted.shutdown()


async def test_a_failed_boot_shuts_down_what_booted_and_propagates() -> None:
    kernel = _kernel(bundles={EchoBundle: {"all": True}, FailingBootBundle: {"all": True}})

    with pytest.raises(RuntimeError, match="boot failed"):
        _ = await kernel.boot()

    assert EVENTS == ["boot:echo", "shutdown:echo"]


async def test_shutdown_errors_are_raised_together() -> None:
    booted = await _kernel(bundles={EchoBundle: {"all": True}}).boot()

    async def broken() -> None:
        raise ValueError("shutdown hook failed")

    booted._on_shutdown = (broken,)

    with pytest.raises(ExceptionGroup) as caught:
        await booted.shutdown()

    assert [str(error) for error in caught.value.exceptions] == ["shutdown hook failed"]
    assert "shutdown:echo" in EVENTS


async def test_booted_kernel_is_an_async_context_manager() -> None:
    async with await _kernel().boot() as booted:
        assert isinstance(await booted.container.get(Greeter), Greeter)

    assert EVENTS[-1] == "shutdown:echo"


async def test_lifespan_boots_and_shuts_down() -> None:
    compiled = _kernel().build()

    async with compiled.lifespan(object()):
        assert "boot:echo" in EVENTS

    assert EVENTS[-1] == "shutdown:echo"


def test_run_injects_main_and_returns_its_exit_code() -> None:
    async def main(greeter: Injected[Greeter]) -> int:
        return len(greeter.greet())

    assert _kernel().run(main) == len("please, HELLO!")
    assert EVENTS[-1] == "shutdown:echo"


def test_run_accepts_a_sync_main() -> None:
    def main() -> int:
        return 3

    assert _kernel().run(main) == 3


def test_run_refuses_a_non_int_result() -> None:
    def main() -> int:
        return "done"  # pyright: ignore[reportReturnType]  # ty: ignore[invalid-return-type]

    with pytest.raises(TypeError, match="not an exit code"):
        _ = _kernel().run(main)


def test_an_env_disabled_bundle_is_reported() -> None:
    compiled = _kernel(
        env="prod",
        bundles={EchoBundle: {"all": True}, DevOnlyBundle: {"dev": True}},
    ).build()

    states = {report.name: report.state for report in compiled.report.bundles}

    assert states["dev_only"] == "env_disabled"


def test_two_kernels_build_independent_containers() -> None:
    first = _kernel().build()
    second = _kernel().build()

    assert first.container is not second.container


def test_a_bundles_module_convention_activates_the_listed_bundle() -> None:
    compiled = Kernel("tests.fixtures.app_with_bundles", env="dev").build()

    names = {report.name for report in compiled.report.bundles if report.state == "active"}
    assert "listed" in names
    assert "kernel" in names
    assert ListedBundle in {type(bundle) for bundle in compiled._bundles}


def test_an_app_service_cannot_override_a_kernel_registered_service() -> None:
    kernel = Kernel("tests.fixtures.app_kernel_clash", env="dev", bundles={})

    with pytest.raises(DuplicateServiceError) as caught:
        _ = kernel.build()

    assert caught.value.first.kind == "kernel"
    assert caught.value.second.kind == "app"


def test_a_package_without_bundles_module_yields_only_the_kernel_bundle() -> None:
    compiled = Kernel("tests.fixtures.app_kernel", env="dev", resources=()).build()

    active = {report.name for report in compiled.report.bundles if report.state == "active"}
    assert active == {"kernel"}
