"""Executable dependency rules for the feature-first modular monolith."""

import ast
from pathlib import Path
import unittest

import labelimg


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "labelimg"

LEGACY_MODULES = {
    "annotation_document.py",
    "annotation_editing.py",
    "annotation_history.py",
    "annotation_persistence.py",
    "annotation_review.py",
    "annotation_session.py",
    "annotation_storage.py",
    "annotation_workspace.py",
    "app.py",
    "canvas.py",
    "constants.py",
    "file_list.py",
    "file_operations.py",
    "file_recovery.py",
    "i18n.py",
    "resources.py",
    "selection.py",
    "settings.py",
    "shape.py",
    "translations.py",
    "ustr.py",
    "utils.py",
}


def python_files(root):
    return tuple(sorted(root.rglob("*.py")))


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


class ModularArchitectureTest(unittest.TestCase):
    def test_root_package_contains_only_entry_and_metadata_modules(self):
        root_modules = {path.name for path in PACKAGE_ROOT.glob("*.py")}
        self.assertEqual(root_modules, {"__init__.py", "__main__.py"})

    def test_legacy_flat_modules_do_not_return(self):
        self.assertFalse(LEGACY_MODULES & {path.name for path in PACKAGE_ROOT.glob("*.py")})
        all_imports = {
            imported
            for path in python_files(PACKAGE_ROOT)
            for imported in imports(path)
        }
        forbidden = {f"labelimg.{name[:-3]}" for name in LEGACY_MODULES}
        self.assertFalse(forbidden & all_imports)

    def test_domain_and_application_layers_are_qt_free(self):
        roots = (
            PACKAGE_ROOT / "annotations" / "domain",
            PACKAGE_ROOT / "annotations" / "application",
            PACKAGE_ROOT / "files" / "application",
            PACKAGE_ROOT / "image_tools" / "domain",
            PACKAGE_ROOT / "image_tools" / "application",
        )
        violations = []
        for root in roots:
            for path in python_files(root):
                for imported in imports(path):
                    if imported.startswith(("PyQt", "labelimg.ui", "labelimg.workbench")):
                        violations.append(f"{path.relative_to(PACKAGE_ROOT)} -> {imported}")
        self.assertEqual(violations, [])

    def test_only_bootstrap_imports_the_concrete_main_window(self):
        importers = []
        for path in python_files(PACKAGE_ROOT):
            if "labelimg.workbench.main_window" in set(imports(path)):
                importers.append(str(path.relative_to(PACKAGE_ROOT)))
        self.assertEqual(importers, ["workbench\\bootstrap.py"])

    def test_numeric_image_dependencies_are_owned_by_image_tools(self):
        violations = []
        for path in python_files(PACKAGE_ROOT):
            if "image_tools" in path.parts:
                continue
            for imported in imports(path):
                if imported.split(".", 1)[0] in {"cv2", "numpy", "PIL"}:
                    violations.append(f"{path.relative_to(PACKAGE_ROOT)} -> {imported}")
        self.assertEqual(violations, [])

    def test_production_code_has_no_wildcard_imports(self):
        violations = []
        for path in python_files(PACKAGE_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                isinstance(node, ast.ImportFrom)
                and any(alias.name == "*" for alias in node.names)
                for node in ast.walk(tree)
            ):
                violations.append(str(path.relative_to(PACKAGE_ROOT)))
        self.assertEqual(violations, [])

    def test_generic_dumping_ground_packages_are_absent(self):
        for name in ("common", "core", "utils"):
            self.assertFalse((PACKAGE_ROOT / name).exists())

    def test_version_and_console_entry_are_the_2_0_contract(self):
        self.assertEqual(labelimg.__version__, "2.0.0")
        project = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(
            'labelImg = "labelimg.workbench.bootstrap:main"',
            project,
        )


if __name__ == "__main__":
    unittest.main()
