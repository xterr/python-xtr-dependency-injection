"""The layering of §5 and the wireup import rule of §9.4, read from every module's AST."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGE = "xtr_dependency_injection"
BRIDGE = f"{PACKAGE}.compiler._wireup_bridge"
PUBLIC_WIREUP = {"wireup", "wireup.errors"}

# What each layer may import at runtime, beyond itself. "exception" is the
# leaf every layer may raise from.
ALLOWED: dict[str, set[str]] = {
    "exception": set(),
    "decorator": {
        "exception",
        "diagnostics",
        "builder.definition",
        "builder.on_invalid",
        "compiler.compiler_pass_interface",
        "compiler.pass_stage",
    },
    "bundle": {"exception", "diagnostics"},
    "runtime": {
        "exception",
        "builder.definition",
        "compiler._wireup_bridge",
        "config.env_placeholder",
    },
    "compiler": {"exception", "decorator.autowire", "config.env_placeholder"},
    "diagnostics": {"exception", "builder.definition"},
    "parameter_bag": {"exception", "config._walk", "config.env_placeholder"},
}
ABOVE_EVERYTHING = {"integration", "kernel", "testing"}

# The compiler passes, the pass config and the compiler live under compiler/.
# Only these modules may reach into builder/, bundle/, config/, decorator/ and
# scan/; each set is the module's complete runtime import contract beyond
# compiler/ itself, and none may import wireup. Every other compiler module
# keeps ALLOWED above.
_PASS_MODULE_IMPORTS: dict[str, set[str]] = {
    "attribute_autoconfiguration_pass": {"builder._origins", "builder.definition"},
    "autowire_as_decorator_pass": {
        "builder._origins",
        "builder.definition",
        "decorator.as_decorator",
    },
    "check_alias_validity_pass": {"exception"},
    "check_definition_validity_pass": {
        "builder.definition",
        "config.env_placeholder",
        "exception",
    },
    "register_env_var_processors_pass": {"builder.definition", "exception", "runtime"},
    "validate_env_placeholders_pass": {"config.env_placeholder", "exception"},
    "resolve_parameter_placeholders_pass": set(),
    "compiler": {"builder._origins", "bundle", "exception"},
    "decorator_service_pass": {"builder.definition", "decorator.as_decorator", "exception"},
    "merge_extension_configuration_pass": {
        "builder._origins",
        "builder.conflict_policy",
        "builder.container_builder",
        "builder.definition",
        "builder.service_configurator",
        "bundle",
        "config.config_resolver",
        "decorator.as_alias",
        "decorator.as_service",
        "decorator.as_tagged_item",
        "decorator.remove_if_missing",
        "scan.scanner",
    },
    "register_autoconfigure_attributes_pass": {
        "builder.autoconfigure_rule",
        "decorator.autoconfigure",
        "exception",
    },
    "remove_missing_dependencies_pass": {"decorator.remove_if_missing", "exception"},
    "replace_alias_by_actual_definition_pass": {"builder.definition", "exception"},
    "resettable_service_pass": {"exception"},
    "resolve_instanceof_conditionals_pass": {"exception"},
    "resolve_references_to_aliases_pass": {"exception"},
}
COMPILER_PASS_MODULES: dict[str, set[str]] = {
    f"{PACKAGE}.compiler.{name}": imports for name, imports in _PASS_MODULE_IMPORTS.items()
}


def _modules() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in sorted((SRC / PACKAGE).rglob("*.py")):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            del parts[-1]
        found.append((".".join(parts), path))
    return found


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _imports(module: str, path: Path, *, runtime_only: bool) -> set[str]:
    tree = ast.parse(path.read_text())
    is_package = path.name == "__init__.py"
    base = module.split(".") if is_package else module.split(".")[:-1]
    found: set[str] = set()

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and _is_type_checking(node):
                if not runtime_only:
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    anchor = base[: len(base) - node.level + 1]
                    target = ".".join([*anchor, node.module] if node.module else anchor)
                else:
                    target = node.module or ""
                found.add(target)
                found.update(f"{target}.{alias.name}" for alias in node.names)
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                visit(node.body)
                visit(getattr(node, "orelse", []))

    visit(tree.body)
    return found


def _layer(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else ""


def _internal(target: str) -> str | None:
    if not target.startswith(f"{PACKAGE}."):
        return None
    return target.removeprefix(f"{PACKAGE}.")


MODULES = _modules()


@pytest.mark.parametrize(("module", "path"), MODULES, ids=[m for m, _ in MODULES])
def test_only_the_bridge_reaches_past_wireups_public_api(module: str, path: Path) -> None:
    if module == BRIDGE:
        return
    wireup = {
        target
        for target in _imports(module, path, runtime_only=False)
        if target == "wireup" or target.startswith("wireup.")
    }
    private = {
        target
        for target in wireup
        if target not in PUBLIC_WIREUP and target.rsplit(".", 1)[0] not in PUBLIC_WIREUP
    }

    assert private == set()
    assert "__wireup_registration__" not in path.read_text()


@pytest.mark.parametrize(("module", "path"), MODULES, ids=[m for m, _ in MODULES])
def test_each_layer_imports_only_what_is_below_it(module: str, path: Path) -> None:
    layer = _layer(module)
    internal = {
        name
        for target in _imports(module, path, runtime_only=True)
        if (name := _internal(target)) is not None
    }
    if module in COMPILER_PASS_MODULES:
        allowed = {"compiler", *COMPILER_PASS_MODULES[module]}
        forbidden = {
            name
            for name in internal
            if not any(name == entry or name.startswith(f"{entry}.") for entry in allowed)
        }
        assert forbidden == set()
        return
    if layer in ALLOWED:
        allowed = {layer, *ALLOWED[layer]}
        forbidden = {
            name
            for name in internal
            if not any(name == entry or name.startswith(f"{entry}.") for entry in allowed)
        }
        assert forbidden == set()
    if layer not in ABOVE_EVERYTHING and module != PACKAGE:
        upward = {name for name in internal if name.split(".")[0] in ABOVE_EVERYTHING}
        assert upward == set()


@pytest.mark.parametrize("module", sorted(COMPILER_PASS_MODULES))
def test_the_compiler_passes_never_import_wireup(module: str) -> None:
    path = next(p for m, p in MODULES if m == module)
    wireup = {
        target
        for target in _imports(module, path, runtime_only=False)
        if target == "wireup" or target.startswith("wireup.")
    }
    assert wireup == set()


def test_the_rules_see_every_module() -> None:
    assert BRIDGE in {module for module, _ in MODULES}
    assert set(COMPILER_PASS_MODULES) <= {module for module, _ in MODULES}
    assert len(MODULES) > 50
