from __future__ import annotations

import base64
import re
import sys
import traceback
from enum import Enum
from typing import TYPE_CHECKING, cast

import pytest

from tests.fixtures.import_witness import WITNESSED
from xtr_dependency_injection.exception import (
    EnvPlaceholderError,
    InvalidEnvironmentVariableError,
    MissingEnvironmentVariableError,
)
from xtr_dependency_injection.runtime.env_var_processor import EnvVarProcessor
from xtr_dependency_injection.runtime.env_var_processors_locator import EnvVarProcessorsLocator

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from xtr_dependency_injection.runtime.env_var_loader_interface import EnvVarLoaderInterface

LIMIT = 42
_WITNESSED_MODULE = "tests.fixtures.witnessed_module"


class Level(Enum):
    LOW = "low"


class FakeLoader:
    def __init__(self, values: Mapping[str, str]) -> None:
        self.values: dict[str, str] = dict(values)
        self.loads: int = 0

    def load_env_vars(self) -> Mapping[str, str]:
        self.loads += 1
        return dict(self.values)


def _locator(
    environ: Mapping[str, str],
    *,
    loaders: tuple[EnvVarLoaderInterface, ...] = (),
    parameters: Mapping[str, object] | None = None,
) -> EnvVarProcessorsLocator:
    known = dict(parameters or {})
    processor = EnvVarProcessor(environ, loaders, known.__getitem__)
    return EnvVarProcessorsLocator(dict.fromkeys(processor.get_provided_types(), processor))


def _get(expression: str, **environ: str) -> object:
    return _locator(environ).get_env(expression)


@pytest.mark.parametrize(
    ("expression", "raw", "expected"),
    [
        ("VAR", "text", "text"),
        ("string:VAR", "text", "text"),
        ("bool:VAR", "on", True),
        ("bool:VAR", "2", True),
        ("bool:VAR", "off", False),
        ("bool:VAR", "maybe", False),
        ("not:VAR", "true", False),
        ("int:VAR", "42", 42),
        ("int:VAR", "  42  ", 42),
        ("int:VAR", "9007199254740993", 9007199254740993),
        ("int:VAR", "1" + "0" * 400, 10**400),
        ("float:VAR", "1e3", 1000.0),
        ("trim:VAR", "  x \n", "x"),
        ("urlencode:VAR", "a b/c", "a%20b%2Fc"),
        ("base64:VAR", base64.urlsafe_b64encode(b"s3cr?t").decode().rstrip("="), "s3cr?t"),
        ("json:VAR", '{"a": [1]}', {"a": [1]}),
        ("json:VAR", "null", None),
        ("csv:VAR", 'a,"b,c",d', ["a", "b,c", "d"]),
        ("csv:VAR", "", []),
        ("query_string:VAR", "a=1&b=x&b=y", {"a": "1", "b": "y"}),
        (f"const:{__name__}.LIMIT", "ignored", 42),
        ("key:a:json:VAR", '{"a": 7}', 7),
        ("key:1:csv:VAR", "x,y", "y"),
        (f"enum:{__name__}.Level:VAR", "low", Level.LOW),
        ("defined:VAR", "x", True),
    ],
)
def test_each_prefix_produces_its_value(expression: str, raw: str, expected: object) -> None:
    assert _get(expression, VAR=raw) == expected


def test_const_takes_its_target_from_the_expression_not_a_variable_value() -> None:
    # The dotted target is named in the expression itself; a variable named by
    # the same text is never read, so a value there cannot redirect the import.
    assert _get(f"const:{__name__}.LIMIT", **{f"{__name__}.LIMIT": "os.getcwd"}) == 42


def test_url_splits_into_its_parts() -> None:
    parts = _get("url:DSN", DSN="pgsql://us%40r:p%3Ass@db:5432/app?sslmode=on#x")

    assert parts == {
        "scheme": "pgsql",
        "host": "db",
        "port": 5432,
        "user": "us@r",
        "pass": "p:ss",
        "path": "app",
        "query": "sslmode=on",
        "fragment": "x",
    }


def test_file_reads_the_file_the_variable_names(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    _ = secret.write_text('{"token": "t"}')

    assert _get("key:token:json:file:PATH", PATH=str(secret)) == "t"


def test_a_file_that_cannot_be_read_never_leaks_its_path_through_the_traceback(
    tmp_path: Path,
) -> None:
    # The path is the variable's value, so it may be the secret itself.
    # Referenced by name below, so it never appears inline on a traceback frame.
    sensitive = "s3cret-value"
    missing = tmp_path / "absent" / sensitive

    with pytest.raises(InvalidEnvironmentVariableError) as caught:
        _ = _get("file:PATH", PATH=str(missing))

    formatted = "".join(traceback.format_exception(caught.value))
    assert sensitive not in formatted
    assert caught.value.value == str(missing)


def test_a_file_that_is_not_utf_8_is_refused(tmp_path: Path) -> None:
    binary = tmp_path / "secret"
    _ = binary.write_bytes(b"\xf0token")

    with pytest.raises(InvalidEnvironmentVariableError, match="file"):
        _ = _get("file:PATH", PATH=str(binary))


def test_base64_of_bytes_that_are_not_utf_8_keeps_them_out_of_the_traceback() -> None:
    # The decoder names the byte it choked on, which is a byte of the decoded value.
    encoded = base64.urlsafe_b64encode(b"\xf0token").decode()

    with pytest.raises(InvalidEnvironmentVariableError) as caught:
        _ = _get("base64:VAR", VAR=encoded)

    formatted = "".join(traceback.format_exception(caught.value))
    assert "0xf0" not in formatted
    assert caught.value.value == encoded


def test_shuffle_keeps_every_item() -> None:
    shuffled = cast("list[str]", _get("shuffle:csv:VAR", VAR="a,b,c"))

    assert sorted(shuffled) == ["a", "b", "c"]


def test_default_falls_back_to_a_parameter_when_unset_or_empty() -> None:
    locator = _locator({"EMPTY": ""}, parameters={"app.fallback": "from parameter"})

    assert locator.get_env("default:app.fallback:UNSET") == "from parameter"
    assert locator.get_env("default:app.fallback:EMPTY") == "from parameter"
    assert locator.get_env("default::UNSET") is None


def test_resolve_replaces_parameter_references() -> None:
    locator = _locator({"PATH_": "%app.dir%/logs/100%%"}, parameters={"app.dir": "/srv"})

    assert locator.get_env("resolve:PATH_") == "/srv/logs/100%"


def test_resolve_replaces_env_references() -> None:
    locator = _locator({"DSN": "smtp://%env(HOST)%:%env(int:PORT)%", "HOST": "mx", "PORT": "25"})

    assert locator.get_env("resolve:DSN") == "smtp://mx:25"


def test_an_invalid_value_is_kept_out_of_the_error_message() -> None:
    with pytest.raises(InvalidEnvironmentVariableError) as caught:
        _ = _get("int:VAR", VAR="s3cr3t")

    assert "s3cr3t" not in str(caught.value)
    assert caught.value.value == "s3cr3t"


def test_defined_is_false_for_an_unset_or_empty_variable() -> None:
    assert _get("defined:VAR") is False
    assert _get("defined:VAR", VAR="") is False


def test_loaders_answer_what_the_environment_lacks_once_until_reset() -> None:
    loader = FakeLoader({"VAULT_VALUE": "vault"})
    processor = EnvVarProcessor({}, [loader])
    locator = EnvVarProcessorsLocator(dict.fromkeys(processor.get_provided_types(), processor))

    assert locator.get_env("VAULT_VALUE") == "vault"
    assert locator.get_env("VAULT_VALUE") == "vault"
    assert loader.loads == 1
    processor.reset()
    loader.values["VAULT_VALUE"] = "rotated"
    assert locator.get_env("VAULT_VALUE") == "rotated"
    assert loader.loads == 2


def test_an_empty_environment_value_is_asked_of_the_loaders_then_kept() -> None:
    locator = _locator({"VAR": ""}, loaders=(FakeLoader({}),))

    assert locator.get_env("VAR") == ""


def test_the_live_process_environment_is_read_without_an_explicit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = EnvVarProcessor()
    locator = EnvVarProcessorsLocator(dict.fromkeys(processor.get_provided_types(), processor))
    monkeypatch.setenv("XTR_LIVE", "1")

    assert locator.get_env("int:XTR_LIVE") == 1


@pytest.mark.parametrize(
    ("expression", "raw", "error", "match"),
    [
        ("VAR", None, MissingEnvironmentVariableError, "VAR"),
        ("int:VAR", "x", InvalidEnvironmentVariableError, "int"),
        ("float:VAR", "true", InvalidEnvironmentVariableError, "float"),
        ("json:VAR", "{", InvalidEnvironmentVariableError, "json"),
        ("json:VAR", "1", InvalidEnvironmentVariableError, "an object, an array or null"),
        ("base64:VAR", "@@", InvalidEnvironmentVariableError, "base64"),
        ("url:VAR", "no-scheme", InvalidEnvironmentVariableError, "scheme and host"),
        ("const:no.such.CONSTANT", None, InvalidEnvironmentVariableError, "const"),
        ("file:VAR", "/no/such/file", InvalidEnvironmentVariableError, "valid file"),
        ("key:z:json:VAR", '{"a": 1}', MissingEnvironmentVariableError, "json:VAR[z]"),
        ("key:9:csv:VAR", "a", MissingEnvironmentVariableError, "csv:VAR[9]"),
        ("key:a:VAR", "text", InvalidEnvironmentVariableError, "key"),
        ("key:VAR", "x", EnvPlaceholderError, "key:KEY:NAME"),
        (f"enum:{__name__}.Level:VAR", "high", InvalidEnvironmentVariableError, "Level"),
        (f"enum:{__name__}.LIMIT:VAR", "low", EnvPlaceholderError, "is not an Enum"),
        ("enum:VAR", "x", EnvPlaceholderError, "needs a class"),
        ("default:VAR", "x", EnvPlaceholderError, "default:PARAM:NAME"),
        ("int:VAR", "4.9", InvalidEnvironmentVariableError, "int"),
        ("int:VAR", "0x1f", InvalidEnvironmentVariableError, "int"),
        ("int:VAR", "1_0", InvalidEnvironmentVariableError, "int"),
        ("int:VAR", "+-1", InvalidEnvironmentVariableError, "int"),
        ("int:json:VAR", "[1]", InvalidEnvironmentVariableError, "int"),
        ("shuffle:VAR", "a", InvalidEnvironmentVariableError, "shuffle"),
        ("nope:VAR", "x", EnvPlaceholderError, "unsupported env var prefix 'nope'"),
    ],
)
def test_a_value_a_prefix_cannot_process_is_refused(
    expression: str, raw: str | None, error: type[Exception], match: str
) -> None:
    environ = {} if raw is None else {"VAR": raw}

    with pytest.raises(error, match=re.escape(match)):
        _ = _locator(environ).get_env(expression)


def test_parameters_are_unavailable_without_a_lookup() -> None:
    processor = EnvVarProcessor({})
    locator = EnvVarProcessorsLocator(dict.fromkeys(processor.get_provided_types(), processor))

    with pytest.raises(EnvPlaceholderError, match="parameters are not available"):
        _ = locator.get_env("default:app.x:UNSET")


def test_resolve_refuses_a_non_scalar_parameter() -> None:
    locator = _locator({"VAR": "%app.list%"}, parameters={"app.list": [1]})

    with pytest.raises(InvalidEnvironmentVariableError, match="resolve"):
        _ = locator.get_env("resolve:VAR")


@pytest.mark.parametrize(
    ("embedded", "refused"),
    [
        (f"const:{_WITNESSED_MODULE}.MARKER", "const"),
        (f"enum:{_WITNESSED_MODULE}.MARKER:VAR", "enum"),
        (f"int:const:{_WITNESSED_MODULE}.MARKER", "const"),
        ("file:OTHER", "file"),
        ("default:app.fallback:OTHER", "default"),
        ("resolve:OTHER", "resolve"),
        ("key:0:csv:OTHER", "key"),
    ],
)
def test_resolve_refuses_a_prefix_a_value_may_not_steer(embedded: str, refused: str) -> None:
    # The expression is source-controlled, its value is not: a variable holding
    # "%env(const:...)%" would otherwise import whatever module it names.
    locator = _locator({"VAR": f"prefix-%env({embedded})%"}, parameters={"app.fallback": "x"})

    with pytest.raises(EnvPlaceholderError, match=re.escape(repr(refused))):
        _ = locator.get_env("resolve:VAR")

    assert WITNESSED == []
    assert _WITNESSED_MODULE not in sys.modules


def test_resolve_still_replaces_the_prefixes_a_value_may_use() -> None:
    locator = _locator({"DSN": "%env(trim:HOST)%:%env(int:PORT)%", "HOST": " mx ", "PORT": "25"})

    assert locator.get_env("resolve:DSN") == "mx:25"


def test_an_enum_class_that_cannot_be_imported_names_the_class_and_the_prefix() -> None:
    with pytest.raises(InvalidEnvironmentVariableError) as caught:
        _ = _get("enum:no.such.Level:VAR", VAR="low")

    assert caught.value.name == "no.such.Level"
    assert caught.value.cast == "enum"


def test_a_sequence_read_with_a_name_instead_of_an_index_is_refused() -> None:
    with pytest.raises(InvalidEnvironmentVariableError, match="key"):
        _ = _get("key:host:csv:VAR", VAR="a,b")


def test_bytes_are_not_a_sequence_a_key_can_read() -> None:
    processor = EnvVarProcessor({})

    with pytest.raises(InvalidEnvironmentVariableError, match="key"):
        _ = processor.get_env("key", "0:RAW", lambda _name: b"ab")


def test_json_that_cannot_be_decoded_keeps_neither_the_text_nor_the_decoders_complaint() -> None:
    # The decoder's message quotes where it stopped, and the text is the value.
    truncated = '{"token": "s3cr3t"'

    with pytest.raises(InvalidEnvironmentVariableError) as caught:
        _ = _get("json:VAR", VAR=truncated)

    formatted = "".join(traceback.format_exception(caught.value))
    assert "s3cr3t" not in formatted
    assert "s3cr3t" not in caught.value.value
    assert caught.value.__cause__ is None


def test_the_processor_provides_every_documented_prefix() -> None:
    assert set(EnvVarProcessor.get_provided_types()) == {
        "base64",
        "bool",
        "not",
        "const",
        "csv",
        "file",
        "float",
        "int",
        "json",
        "key",
        "url",
        "query_string",
        "resolve",
        "default",
        "string",
        "trim",
        "enum",
        "shuffle",
        "defined",
        "urlencode",
    }
