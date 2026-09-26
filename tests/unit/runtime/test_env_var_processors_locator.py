from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from xtr_dependency_injection.exception import EnvPlaceholderError
from xtr_dependency_injection.runtime.env_var_processors_locator import EnvVarProcessorsLocator

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class Recording:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_env(self, prefix: str, name: str, get_env: Callable[[str], object]) -> object:
        self.calls.append((prefix, name))
        return f"{prefix}({get_env(name) if ':' in name else name})"

    @classmethod
    def get_provided_types(cls) -> Mapping[str, str]:
        return {"string": "string", "upper": "string"}


def test_no_prefix_is_the_string_prefix() -> None:
    recording = Recording()

    assert EnvVarProcessorsLocator({"string": recording}).get_env("VAR") == "string(VAR)"
    assert recording.calls == [("string", "VAR")]


def test_a_chain_is_run_outermost_first_each_prefix_resolving_the_rest() -> None:
    recording = Recording()
    locator = EnvVarProcessorsLocator({"string": recording, "upper": recording})

    assert locator.get_env("upper:string:VAR") == "upper(string(VAR))"
    assert recording.calls == [("upper", "string:VAR"), ("string", "VAR")]


def test_a_prefix_no_processor_provides_is_refused() -> None:
    with pytest.raises(EnvPlaceholderError, match="unsupported env var prefix 'upper'"):
        _ = EnvVarProcessorsLocator({"string": Recording()}).get_env("upper:VAR")


def test_it_lists_its_prefixes() -> None:
    recording = Recording()

    assert EnvVarProcessorsLocator({"string": recording, "upper": recording}).prefixes() == (
        "string",
        "upper",
    )
