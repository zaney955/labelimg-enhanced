"""Deterministic PyInstaller inventory for this repository's local package."""

import ast
from pathlib import Path


def local_package_modules(package_root):
    """Return import names for every Python module below one package root."""
    package_root = Path(package_root)
    package_name = package_root.name
    modules = []
    for path in package_root.rglob("*.py"):
        relative = path.relative_to(package_root)
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts.pop()
        else:
            parts[-1] = Path(parts[-1]).stem
        modules.append(".".join((package_name, *parts)).rstrip("."))
    return sorted(set(modules))


def dynamic_export_modules(source):
    """Read constant module targets from a lazy public-export initializer."""
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if not any(
            isinstance(target, ast.Name) and target.id == "_EXPORT_MODULES"
            for target in targets
        ):
            continue
        value = ast.literal_eval(node.value)
        return tuple(sorted(set(value.values())))
    return ()


__all__ = ("dynamic_export_modules", "local_package_modules")
