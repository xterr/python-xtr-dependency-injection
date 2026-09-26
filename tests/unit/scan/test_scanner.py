from __future__ import annotations

import pytest

from tests.fixtures.app_scan import hooks, services
from xtr_dependency_injection.exception import ConfigProviderError, ResourceImportError
from xtr_dependency_injection.scan import DEFAULT_EXCLUDES
from xtr_dependency_injection.scan.scanned_object import ScannedObject
from xtr_dependency_injection.scan.scanner import Scanner, ScanResult

APP = "tests.fixtures.app_scan"


class First:
    pass


class Second:
    pass


def _scanned(obj: object, order: int) -> ScannedObject:
    return ScannedObject(obj, f"tests:{getattr(obj, '__qualname__', obj)}", None, order)


def test_extend_keeps_every_queue_in_order() -> None:
    first = ScanResult(services=[_scanned(First, order=1)])
    second = ScanResult(services=[_scanned(Second, order=2)], marked=[_scanned(Second, order=2)])

    first.extend(second)

    assert [entry.obj for entry in first.services] == [First, Second]
    assert [entry.obj for entry in first.marked] == [Second]


def _scanner(env: str = "dev") -> Scanner:
    return Scanner(env=env, exclude=DEFAULT_EXCLUDES)


def test_a_package_is_walked_recursively_in_name_order() -> None:
    scanner = _scanner()

    _ = scanner.scan([APP], owner=None)

    assert scanner.modules == [
        APP,
        f"{APP}.alpha",
        f"{APP}.environments",
        f"{APP}.helpers",
        f"{APP}.hooks",
        f"{APP}.services",
        f"{APP}.sub",
        f"{APP}.sub.zeta",
    ]


def test_a_plain_module_is_just_itself() -> None:
    scanner = _scanner()

    _ = scanner.scan([f"{APP}.alpha"], owner=None)

    assert scanner.modules == [f"{APP}.alpha"]


def test_only_objects_defined_in_a_module_are_candidates() -> None:
    result = _scanner().scan([f"{APP}.services"], owner=None)

    assert [scanned.obj for scanned in result.services] == [
        services.Marked,
        services.Plain,
        services.plain_function,
    ]


def test_a_marked_object_is_marked_and_a_service() -> None:
    result = _scanner().scan([f"{APP}.services"], owner=None)

    assert [scanned.obj for scanned in result.marked] == [services.Marked]


def test_an_object_is_found_once_across_scans() -> None:
    scanner = _scanner()
    first = scanner.scan([f"{APP}.services"], owner=None)

    second = scanner.scan([f"{APP}.services"], owner="alpha", late=True)

    assert len(first.services) == 3
    assert second.services == []


def test_scan_order_is_total_across_scans() -> None:
    scanner = _scanner()
    first = scanner.scan([f"{APP}.alpha"], owner=None)

    second = scanner.scan([f"{APP}.sub"], owner="alpha", late=True)

    assert first.services[0].order < second.services[0].order
    assert second.services[0].owner == "alpha"


def test_an_object_outside_the_env_is_skipped_and_reported() -> None:
    scanner = _scanner("prod")

    result = scanner.scan([f"{APP}.environments"], owner=None)

    assert [scanned.name for scanned in result.services] == [f"{APP}.environments:NotInDev"]
    assert scanner.skipped == [(f"{APP}.environments:dev_only", "@when(dev) excludes 'prod'")]


def test_when_not_is_reported_with_its_reason() -> None:
    scanner = _scanner("dev")

    _ = scanner.scan([f"{APP}.environments"], owner=None)

    assert scanner.skipped == [(f"{APP}.environments:NotInDev", "@when_not(dev) excludes 'dev'")]


def test_every_queue_marker_goes_to_its_queue() -> None:
    result = _scanner().scan([f"{APP}.hooks"], owner=None)

    assert [s.obj for s in result.configure] == [hooks.configured]
    assert [s.obj for s in result.parameters] == [hooks.provided]
    assert [s.obj for s in result.compiler_passes] == [hooks.Adjusted]
    assert [s.obj for s in result.on_boot] == [hooks.booted]
    assert [s.obj for s in result.on_shutdown] == [hooks.stopped]
    assert [s.obj for s in result.decorators] == [hooks.Wrapping]
    assert [s.obj for s in result.services] == [hooks.Target]


def test_a_late_scan_refuses_config_providers() -> None:
    with pytest.raises(ConfigProviderError, match="@configure was found by a scan requested"):
        _ = _scanner().scan([f"{APP}.hooks"], owner="alpha", late=True)


def test_two_queue_markers_on_one_object_are_refused() -> None:
    with pytest.raises(ConfigProviderError, match="@configure and @on_boot exclude each other"):
        _ = _scanner().scan(["tests.fixtures.app_double_marker"], owner=None)


def test_a_module_failing_to_import_is_reported() -> None:
    with pytest.raises(ResourceImportError) as caught:
        _ = _scanner().scan(["tests.fixtures.app_broken"], owner=None)

    assert caught.value.module == "tests.fixtures.app_broken.broken"
    assert isinstance(caught.value.__cause__, ImportError)


def test_custom_excludes_replace_the_defaults() -> None:
    scanner = Scanner(
        env="dev", exclude=(f"{APP}.sub", "*.tests", "*.test_*", "*.conftest", "*.__main__")
    )

    _ = scanner.scan([APP], owner=None)

    assert f"{APP}.sub" not in scanner.modules
    assert f"{APP}.alpha" in scanner.modules


def test_a_module_object_is_accepted_as_a_resource() -> None:
    scanner = _scanner()

    result = scanner.scan([services], owner=None)

    assert services.Plain in [scanned.obj for scanned in result.services]
