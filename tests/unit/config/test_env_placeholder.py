from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from typing import NamedTuple

import pytest

from xtr_dependency_injection.config import env
from xtr_dependency_injection.config.env_placeholder import (
    ENV_PARAMETERS_ROOT,
    EnvPlaceholder,
    env_parameter,
    env_placeholders_embedded_in,
    env_placeholders_in,
    env_tokens,
    placeholder,
    resolve_env_placeholders,
)
from xtr_dependency_injection.exception import EnvPlaceholderError

VALUES: dict[str, object] = {
    "HOST": "db.local",
    "int:PORT": 5432,
    "json:OPTIONS": {"ssl": True},
    "bool:DEBUG": True,
}


def _get_env(expression: str) -> object:
    return VALUES[expression]


@dataclass(frozen=True)
class Transport:
    dsn: str
    port: int = 0

    def __post_init__(self) -> None:
        if self.port < 0:
            msg = "port must not be negative"
            raise ValueError(msg)


@dataclass(frozen=True)
class Config:
    transports: dict[str, Transport] = field(default_factory=dict)
    hosts: tuple[str, ...] = ()
    untouched: list[str] = field(default_factory=list)


class Pair(NamedTuple):
    left: object
    right: object


def test_one_spec_makes_one_placeholder() -> None:
    assert env("HOST") is env("HOST")
    assert env("HOST") is not env("HOST", default="x")


def test_a_placeholder_is_an_instance_of_its_type_where_python_allows_it() -> None:
    assert isinstance(env("HOST"), str)
    assert isinstance(env("PORT", int), int)
    assert isinstance(env("RATIO", float), float)
    assert not isinstance(env("DEBUG", bool), bool)


def test_a_placeholder_renders_as_its_token_and_repr_names_it() -> None:
    port = env("PORT", int)
    assert isinstance(port, EnvPlaceholder)

    assert f"{port}" == port.token
    assert str(port) == port.token
    assert repr(port) == "env(int:PORT)"


def test_a_placeholder_cannot_decide_structure() -> None:
    with pytest.raises(EnvPlaceholderError, match="cannot decide"):
        _ = bool(env("DEBUG", bool))


def test_a_placeholder_survives_pickling_as_itself() -> None:
    port = env("PORT", int)

    assert pickle.loads(pickle.dumps(port)) is port  # noqa: S301 — our own object.


def test_config_validation_runs_against_the_default_while_building() -> None:
    with pytest.raises(ValueError, match="negative"):
        _ = Transport("x", env("PORT", int, default=-1))


def test_placeholders_are_found_everywhere_a_config_holds_them() -> None:
    config = Config(
        transports={"db": Transport(f"pg://{env('HOST')}", env("PORT", int))},
        hosts=(env("HOST"),),
    )

    found = {held.expression for held in env_placeholders_in(config)}

    assert found == {"HOST", "int:PORT"}


def test_only_placeholders_inside_longer_strings_count_as_embedded() -> None:
    config = Config(hosts=(env("HOST"), f"{env('HOST')}:{env('PORT', int)}"))

    embedded = {held.expression for held in env_placeholders_embedded_in(config)}

    assert embedded == {"HOST", "int:PORT"}
    assert env_placeholders_embedded_in(env("HOST")) == []


def test_resolution_rebuilds_only_what_holds_a_placeholder() -> None:
    untouched = ["kept"]
    config = Config(
        transports={"db": Transport(f"pg://{env('HOST')}:{env('PORT', int)}", env("PORT", int))},
        hosts=(env("HOST"), "static"),
        untouched=untouched,
    )

    resolved = resolve_env_placeholders(config, _get_env)

    assert isinstance(resolved, Config)
    assert resolved.transports == {"db": Transport("pg://db.local:5432", 5432)}
    assert resolved.hosts == ("db.local", "static")
    assert resolved.untouched is untouched


def test_a_named_tuple_and_a_set_are_rebuilt_as_themselves() -> None:
    resolved = resolve_env_placeholders((Pair(env("HOST"), 1), {env("HOST")}), _get_env)

    assert resolved == (Pair("db.local", 1), {"db.local"})
    assert isinstance(resolved, tuple)
    assert isinstance(resolved[0], Pair)


def test_a_value_without_placeholders_is_returned_as_is() -> None:
    config = Config(hosts=("a",))

    assert resolve_env_placeholders(config, _get_env) is config
    assert env_placeholders_in(config) == []


def test_a_bare_token_string_resolves_to_the_typed_value() -> None:
    port = env("PORT", int)

    assert resolve_env_placeholders(str(port), _get_env) == 5432


def test_a_non_scalar_cannot_be_embedded_in_a_string() -> None:
    with pytest.raises(EnvPlaceholderError, match="cannot be embedded"):
        _ = resolve_env_placeholders(f"opts={env('json:OPTIONS')}", _get_env)


def test_each_placeholder_is_resolved_once_per_resolution() -> None:
    calls: list[str] = []

    def counting(expression: str) -> object:
        calls.append(expression)
        return _get_env(expression)

    _ = resolve_env_placeholders([env("HOST"), env("HOST"), f"{env('HOST')}"], counting)

    assert calls == ["HOST"]


def test_every_autowire_env_expression_has_a_parameter_in_the_tokens_mapping() -> None:
    key = env_parameter("int:WORKERS")
    root, _, token = key.partition(".")

    assert root == ENV_PARAMETERS_ROOT
    assert token in env_tokens()
    assert env_tokens()[token] is placeholder("int:WORKERS")
    assert token in list(env_tokens())
    assert len(env_tokens()) >= 1


def test_a_string_placeholder_holds_its_default_for_validation_and_renders_its_token() -> None:
    dsn = env("QUEUE_DSN", default="sync://")
    assert isinstance(dsn, EnvPlaceholder)

    assert dsn.startswith("sync://")
    assert str(dsn) == dsn.token
    assert f"{dsn}/x" == f"{dsn.token}/x"
    assert resolve_env_placeholders(dsn, lambda _expression: "amqp://rabbit") == "amqp://rabbit"


def test_a_value_holding_another_token_is_not_resolved_again() -> None:
    host = placeholder("string:HOST_A")
    other = placeholder("string:HOST_B")
    values = {"string:HOST_A": str(other), "string:HOST_B": "b"}

    resolved = resolve_env_placeholders(f"{host}-{other}", values.__getitem__)

    assert resolved == f"{other}-b"


def test_a_string_looking_like_a_token_is_left_alone() -> None:
    host = placeholder("string:LOOKALIKE")
    forged = f"env_string_LOOKALIKE_{'0' * 32}"

    assert forged != host.token
    assert resolve_env_placeholders(forged, lambda _: "x") == forged
    assert env_placeholders_in(forged) == []


def test_a_token_run_into_preceding_text_is_still_found() -> None:
    host = placeholder("string:GLUED")

    resolved = resolve_env_placeholders(f"env_x_{host}/path", lambda _: "h")

    assert resolved == "env_x_h/path"
