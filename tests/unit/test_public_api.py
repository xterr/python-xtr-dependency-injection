from __future__ import annotations

import inspect
import tomllib
from pathlib import Path
from typing import Annotated, cast, get_args, get_origin, get_type_hints

import wireup

import xtr_dependency_injection
import xtr_dependency_injection.diagnostics
import xtr_dependency_injection.exception
import xtr_dependency_injection.testing
from xtr_dependency_injection.integration import wireup as integration_wireup

PUBLIC = {
    "Kernel",
    "CompiledKernel",
    "BootedKernel",
    "KernelInterface",
    "Bundle",
    "NoConfig",
    "as_bundle",
    "BundleMetadata",
    "ServiceConfigurator",
    "ContainerBuilder",
    "Decorates",
    "Definition",
    "ServiceKey",
    "Origin",
    "configure",
    "parameters",
    "env",
    "when",
    "when_not",
    "exclude",
    "compiler_pass",
    "on_boot",
    "on_shutdown",
    "as_alias",
    "as_decorator",
    "as_service",
    "as_tagged_item",
    "autoconfigure",
    "autoconfigure_tag",
    "AliasOf",
    "Autowire",
    "AutowireDecorated",
    "Injected",
    "OnInvalid",
    "Target",
    "bind_callable",
    "bundle_active",
    "qualified_name",
    "ServiceLocator",
    "ServicesResetter",
    "RequiredBundle",
    "required_bundle",
    "DEFAULT_EXCLUDES",
    "KernelReport",
    "PassStage",
    "remove_if_missing",
}


def test_the_public_api_is_exactly_what_the_plan_lists() -> None:
    assert set(xtr_dependency_injection.__all__) == PUBLIC


def test_every_public_name_is_importable() -> None:
    for name in PUBLIC:
        assert getattr(xtr_dependency_injection, name) is not None


def test_the_version_comes_from_the_distribution() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    data: dict[str, dict[str, object]] = tomllib.loads(pyproject.read_text())

    assert xtr_dependency_injection.__version__ == data["project"]["version"]


def _engine_types_in(annotation: object, seen: set[int] | None = None) -> list[str]:
    """Walk ``annotation`` and return the names of every wireup type it references."""
    seen = seen if seen is not None else set()
    if id(annotation) in seen:
        return []
    seen.add(id(annotation))
    hits: list[str] = []
    module: object = getattr(annotation, "__module__", "")
    if isinstance(module, str) and module.startswith("wireup"):
        qualname = getattr(annotation, "__qualname__", None) or getattr(
            annotation, "__name__", repr(annotation)
        )
        hits.append(f"{module}:{qualname}")
    origin = get_origin(annotation)
    if origin is Annotated:
        for arg in cast("tuple[object, ...]", get_args(annotation)):
            hits.extend(_engine_types_in(arg, seen))
    elif origin is not None:
        hits.extend(_engine_types_in(cast("object", origin), seen))
        for arg in cast("tuple[object, ...]", get_args(annotation)):
            hits.extend(_engine_types_in(arg, seen))
    return hits


def _hints_of(obj: object) -> dict[str, object]:
    try:
        return get_type_hints(obj, include_extras=True)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — a hint that cannot be resolved cannot leak the engine.
        return {}


def _public_objects() -> list[tuple[str, object]]:
    modules = (
        xtr_dependency_injection,
        xtr_dependency_injection.testing,
        xtr_dependency_injection.exception,
        xtr_dependency_injection.diagnostics,
    )
    found: list[tuple[str, object]] = []
    for module in modules:
        for name in module.__all__:  # pyright: ignore[reportAny]
            obj: object = getattr(module, name)  # pyright: ignore[reportAny]
            found.append((f"{module.__name__}.{name}", obj))
    return found


def test_no_public_signature_mentions_the_engine() -> None:
    leaks: list[str] = []
    for label, obj in _public_objects():
        for hint_name, hint in _hints_of(obj).items():
            leaks.extend(f"{label} :: {hint_name} -> {hit}" for hit in _engine_types_in(hint))
        if inspect.isclass(obj):
            for method_name, method in inspect.getmembers(obj, predicate=inspect.isfunction):
                if method_name.startswith("_") and method_name != "__init__":
                    continue
                for hint_name, hint in _hints_of(method).items():
                    leaks.extend(
                        f"{label}.{method_name} :: {hint_name} -> {hit}"
                        for hit in _engine_types_in(hint)
                    )

    assert leaks == [], "public signatures leaking the engine:\n" + "\n".join(leaks)


def test_the_no_engine_public_signature_guard_can_fail() -> None:
    def leaky() -> object:  # placeholder to attach a synthetic annotation
        raise NotImplementedError

    leaky.__annotations__ = {"return": wireup.AsyncContainer}

    hits = _engine_types_in(get_type_hints(leaky).get("return"))

    assert hits, "the guard failed to detect a wireup return type"


def test_engine_container_returns_the_engine() -> None:
    sig = inspect.signature(integration_wireup.engine_container, eval_str=False)
    ret: object = sig.return_annotation  # pyright: ignore[reportAny]

    assert ret in ("AsyncContainer", wireup.AsyncContainer)
