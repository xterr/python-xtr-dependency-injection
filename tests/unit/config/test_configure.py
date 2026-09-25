from __future__ import annotations

from xtr_dependency_injection.config.configure import ConfigureMarker, configure, configure_of


def test_a_bare_configure_has_priority_zero() -> None:
    @configure
    def provide() -> int:
        return 1

    assert configure_of(provide) == ConfigureMarker(0)


def test_configure_records_its_priority() -> None:
    @configure(priority=4)
    def provide() -> int:
        return 1

    assert configure_of(provide) == ConfigureMarker(4)


def test_an_unmarked_function_is_not_configured() -> None:
    def provide() -> int:
        return 1

    assert configure_of(provide) is None
