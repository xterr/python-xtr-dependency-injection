"""An unknown-dependency compilation failure is reworded to name the fix.

wireup raises a bare ``WireupError`` whose only data is a formatted string, so
the compiler parses that string; anything it does not recognise keeps the
engine's message verbatim, and the engine error stays reachable as
``__cause__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import pytest
from typing_extensions import override
from wireup.errors import WireupError

from xtr_dependency_injection import Bundle, Kernel, ServiceConfigurator, as_bundle
from xtr_dependency_injection.compiler.wireup_compiler import _compilation_reason
from xtr_dependency_injection.exception import ContainerCompilationError

if TYPE_CHECKING:
    from xtr_dependency_injection.builder.container_builder import ContainerBuilder

APP = "tests.fixtures.app_empty"


def test_a_plain_unknown_dependency_message_names_the_fix() -> None:
    message = (
        "Parameter 'missing' of <class 'shop.Widget'> "
        "has an unknown dependency on <class 'shop.Gadget'>."
    )
    error = WireupError(message)

    reason = _compilation_reason(error)

    assert reason == (
        "shop.Widget.missing needs shop.Gadget, which is not a registered service: "
        "mark it @as_service (or alias it with @as_alias), or register it in a "
        "bundle's load_extension"
    )


def test_a_qualified_unknown_dependency_message_keeps_the_qualifier() -> None:
    message = (
        "Parameter 'dep' of <class 'shop.Widget'> "
        "has an unknown dependency on <class 'shop.Gadget'> with qualifier 'smtp'."
    )
    error = WireupError(message)

    reason = _compilation_reason(error)

    assert reason.startswith("shop.Widget.dep needs shop.Gadget['smtp'], which is not")


def test_an_unrelated_engine_message_is_kept_verbatim() -> None:
    error = WireupError("Something else entirely went wrong.")

    assert _compilation_reason(error) == "Something else entirely went wrong."


class Gadget:
    pass


@final
class Widget:
    def __init__(self, gadget: Gadget) -> None:
        self.gadget = gadget


def test_the_kernel_surfaces_the_reworded_message_with_cause_and_origin() -> None:
    @as_bundle("unknown")
    class UnknownBundle(Bundle):
        @override
        def load_extension(
            self,
            config: object,
            services: ServiceConfigurator,
            builder: ContainerBuilder,
        ) -> None:
            del config, builder
            _ = services.set(Widget)

    kernel = Kernel(APP, resources=(), bundles={UnknownBundle: {"all": True}})

    with pytest.raises(ContainerCompilationError) as caught:
        _ = kernel.build()

    message = str(caught.value)
    assert f"{__name__}.Widget.gadget needs {__name__}.Gadget" in message
    assert "mark it @as_service" in message
    assert isinstance(caught.value.__cause__, WireupError)
    assert any("is defined by" in note for note in caught.value.__notes__)
