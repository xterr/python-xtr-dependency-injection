from __future__ import annotations

from xtr_dependency_injection.config import env
from xtr_dependency_injection.parameter_bag import EnvPlaceholderParameterBag


def test_an_env_reference_is_a_placeholder_typed_when_whole() -> None:
    bag = EnvPlaceholderParameterBag({"app": {"host": "db"}})

    port = bag.resolve_string("%env(int:PORT)%")
    dsn = bag.resolve_string("pg://%app.host%:%env(int:PORT)%")

    assert port is env("int:PORT")
    assert dsn == f"pg://db:{env('int:PORT')}"
    assert bag.get_env_placeholders() == {"int:PORT": env("int:PORT")}


def test_it_records_the_provided_types() -> None:
    bag = EnvPlaceholderParameterBag()
    bag.set_provided_types({"int": "int"})

    assert bag.get_provided_types() == {"int": "int"}
