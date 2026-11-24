from __future__ import annotations

import importlib
import math
import types
from typing import TYPE_CHECKING, cast

import pytest

from xtr_dependency_injection.scan._stand_ins import (
    STAND_IN_ATTRIBUTE,
    StandIn,
    StandInModule,
    unwrapped,
)

if TYPE_CHECKING:
    from tests.support.modules import ScratchModules


def _stand_in(value: object) -> StandIn:
    """Return ``value``, a stand-in by construction, typed as one."""
    assert isinstance(value, StandIn)
    return value


def test_an_attribute_is_another_stand_in_named_after_its_path() -> None:
    stand_in = StandIn("acme_faker")

    providers = _stand_in(stand_in.providers)
    assert repr(providers.person) == "<stand-in for acme_faker.providers.person>"


def test_a_dunder_is_missing_as_on_any_object() -> None:
    with pytest.raises(AttributeError):
        _ = StandIn("acme_faker").__wrapped__


def test_a_call_is_a_stand_in_for_its_result() -> None:
    fake = _stand_in(StandIn("acme_faker.Faker")("en_US", seed=1))

    assert isinstance(_stand_in(fake.name)(), StandIn)


def test_used_as_a_decorator_it_remembers_the_class_it_decorates() -> None:
    class Decorated:
        pass

    assert unwrapped(StandIn("acme_faker.register")(Decorated)) is Decorated


def test_used_as_a_decorator_it_remembers_the_function_it_decorates() -> None:
    def decorated() -> None: ...

    assert unwrapped(StandIn("acme_faker.register")(decorated)) is decorated


def test_a_decorator_factory_handed_a_class_gives_back_what_it_decorates() -> None:
    class Users:
        pass

    class Orders:
        pass

    assert _stand_in(StandIn("acme_tools.depends_on")(Users))(Orders) is Orders


def test_a_remembering_stand_in_reads_what_it_remembers_and_stands_in_for_what_it_lacks() -> None:
    class Decorated:
        pass

    # A class of a module not loaded: the inspected module's, or a set-aside one's.
    Decorated.__module__ = "acme_app.not_loaded"
    remembering = _stand_in(StandIn("acme_faker.register")(Decorated))

    assert remembering.__name__ == "Decorated"
    assert isinstance(remembering.register_trait, StandIn)


def test_a_remembering_stand_in_reads_nothing_of_a_class_of_a_loaded_module() -> None:
    class Loaded:
        @staticmethod
        def delete_all() -> None:
            raise AssertionError

    remembering = _stand_in(StandIn("acme_tools.factory_for")(Loaded))

    assert isinstance(_stand_in(remembering.delete_all)(), StandIn)


def test_a_remembering_stand_in_sets_attributes_on_a_class_of_the_running_module(
    scratch_modules: ScratchModules,
) -> None:
    scratch_modules.write(
        {
            "acme_app.marking": (
                "from xtr_dependency_injection.scan._stand_ins import StandIn\n\n\n"
                "class Decorated:\n    pass\n\n\n"
                "remembering = StandIn('acme_faker.register')(Decorated)\n"
                "remembering.marker = 'set'\n"
            )
        }
    )

    module = importlib.import_module("acme_app.marking")

    assert vars(cast("type", vars(module)["Decorated"]))["marker"] == "set"


def test_a_remembering_stand_in_leaves_a_class_of_another_module_be() -> None:
    class Elsewhere:
        pass

    remembering = _stand_in(StandIn("acme_faker.factory_for")(Elsewhere))
    remembering.count = 5

    assert "count" not in vars(Elsewhere)


def test_stacked_stand_in_decorators_keep_the_class_they_decorate() -> None:
    class Both:
        pass

    inner = StandIn("acme_faker.other")(Both)
    outer = StandIn("acme_faker.register")(inner)

    assert unwrapped(outer) is Both


def test_a_class_derived_from_a_remembering_stand_in_derives_from_what_it_remembers() -> None:
    class Base:
        pass

    # A class of a module not loaded: the inspected module's, or a set-aside one's.
    Base.__module__ = "acme_app.not_loaded"
    # Deriving from what is not a class is the case under test.
    derived = types.new_class("Derived", (StandIn("acme_faker.register")(Base),))  # ty: ignore[invalid-base]

    assert derived.__bases__ == (Base,)


def test_a_class_derived_from_a_stand_in_remembering_a_loaded_class_runs_none_of_its_code() -> None:
    class Loaded:
        def __init_subclass__(cls) -> None:
            raise AssertionError

    # Deriving from what is not a class is the case under test.
    derived = types.new_class("Derived", (StandIn("acme_tools.factory_for")(Loaded),))  # ty: ignore[invalid-base]

    assert Loaded not in derived.__mro__


def test_called_as_a_metaclass_it_builds_the_class() -> None:
    built = StandIn("acme_faker.Meta")("Model", (), {"__module__": "app.models", "x": 1})

    assert isinstance(built, type)
    assert (built.__name__, built.__module__, vars(built)["x"]) == ("Model", "app.models", 1)


def test_called_with_three_arguments_of_other_kinds_it_is_a_stand_in() -> None:
    assert isinstance(StandIn("acme_faker.triple")("a", "b", "c"), StandIn)


def test_it_takes_part_in_arithmetic_comparison_and_counting() -> None:
    stand_in = StandIn("acme_faker.number")

    assert isinstance(stand_in + 1, StandIn)
    assert isinstance(1 - stand_in, StandIn)
    assert isinstance(stand_in > 3, StandIn)
    assert (len(stand_in), int(stand_in), float(stand_in)) == (0, 0, 0.0)
    assert (round(stand_in), math.trunc(stand_in), math.floor(stand_in), math.ceil(stand_in)) == (
        0,
        0,
        0,
        0,
    )
    assert ([7][stand_in], 3 in stand_in) == (7, False)
    with stand_in as entered:
        assert entered is stand_in


def test_nothing_is_an_instance_or_a_subclass_of_it() -> None:
    stand_in = StandIn("acme_faker.Model")

    assert not isinstance(1, stand_in)  # pyright: ignore[reportArgumentType] — a stand-in in place of a class  # ty: ignore[invalid-argument-type]
    assert not issubclass(int, stand_in)  # pyright: ignore[reportArgumentType] — a stand-in in place of a class  # ty: ignore[invalid-argument-type]


def test_items_set_on_it_are_let_be() -> None:
    stand_in = StandIn("acme_faker.settings")
    stand_in["locale"] = "en_US"
    stand_in.seed = 4
    del stand_in["locale"]

    assert repr(stand_in) == "<stand-in for acme_faker.settings>"


def test_a_subscription_and_a_union_are_stand_ins() -> None:
    generic = StandIn("acme_faker.Factory")[int]

    assert isinstance(generic, StandIn)
    assert isinstance(generic | None, StandIn)
    assert isinstance(None | generic, StandIn)


def test_it_iterates_over_nothing() -> None:
    assert list(StandIn("acme_faker.items")) == []


def test_a_class_derived_from_it_has_a_plain_marked_base() -> None:
    # Deriving from what is not a class is the case under test.
    derived = types.new_class("Derived", (StandIn("acme_faker.Factory"),))  # ty: ignore[invalid-base]

    (parent,) = derived.__bases__
    assert getattr(parent, STAND_IN_ATTRIBUTE) == "acme_faker.Factory"
    assert parent.__module__ == "acme_faker"


def test_every_class_derived_from_one_stand_in_shares_its_base() -> None:
    base = StandIn("acme_faker.Factory")

    # Deriving from what is not a class is the case under test.
    first = types.new_class("First", (base,))  # ty: ignore[invalid-base]
    second = types.new_class("Second", (base,))  # ty: ignore[invalid-base]

    assert first.__bases__ == second.__bases__


def test_a_class_derived_from_it_may_be_given_keywords() -> None:
    # Deriving from what is not a class, with a keyword, is the case under test.
    derived = types.new_class(
        "Derived",
        (StandIn("acme_faker.Factory"),),  # ty: ignore[invalid-base]
        {"model": "user"},
    )

    assert derived.__name__ == "Derived"


def test_a_module_answers_every_name_with_a_stand_in() -> None:
    module = StandInModule("acme_faker")

    assert repr(module.Faker) == "<stand-in for acme_faker.Faker>"


def test_a_module_lacks_its_dunders_as_any_module_does() -> None:
    with pytest.raises(AttributeError):
        _ = StandInModule("acme_faker").__all__
