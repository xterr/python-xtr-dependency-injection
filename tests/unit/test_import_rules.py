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
    "decorator": {"exception", "diagnostics"},
    "bundle": {"exception", "diagnostics"},
    "runtime": {"exception", "builder.definition"},
    "compiler": {"exception"},
    "diagnostics": {"exception", "builder.definition"},
}
ABOVE_EVERYTHING = {"kernel", "standalone", "testing"}


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


def test_the_rules_see_every_module() -> None:
    assert BRIDGE in {module for module, _ in MODULES}
    assert len(MODULES) > 50
