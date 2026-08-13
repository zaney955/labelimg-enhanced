"""Executable dependency rules for the feature-first modular monolith."""

import ast
import importlib
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


def package_relative_path(path):
    return path.relative_to(PACKAGE_ROOT).as_posix()


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
        forbidden = {
            f"labelimg.{name[:-3]}"
            for name in LEGACY_MODULES
            if not (PACKAGE_ROOT / name[:-3]).is_dir()
        }
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
                importers.append(package_relative_path(path))
        self.assertEqual(importers, ["workbench/bootstrap.py"])

    def test_feature_dependencies_are_acyclic_and_use_public_exports(self):
        features = {"annotations", "canvas", "files", "image_tools"}
        graph = {feature: set() for feature in features}
        private_imports = []
        for feature in features:
            for path in python_files(PACKAGE_ROOT / feature):
                for imported in imports(path):
                    parts = imported.split(".")
                    if len(parts) < 2 or parts[0] != "labelimg":
                        continue
                    dependency = parts[1]
                    if dependency not in features or dependency == feature:
                        continue
                    graph[feature].add(dependency)
                    if imported != "labelimg.%s" % dependency:
                        private_imports.append(
                            "%s -> %s"
                            % (path.relative_to(PACKAGE_ROOT), imported)
                        )
        self.assertEqual(private_imports, [])

        def reaches(start, current, visited):
            for dependency in graph[current]:
                if dependency == start:
                    return True
                if dependency not in visited and reaches(
                    start, dependency, visited | {dependency}
                ):
                    return True
            return False

        cycles = sorted(
            feature
            for feature in features
            if reaches(feature, feature, {feature})
        )
        self.assertEqual(cycles, [])

    def test_public_feature_exports_are_resolvable(self):
        for feature in ("annotations", "canvas", "files", "image_tools"):
            module = importlib.import_module("labelimg.%s" % feature)
            missing = [
                name for name in module.__all__
                if not hasattr(module, name)
            ]
            self.assertEqual(missing, [], feature)

    def test_bootstrap_owns_launch_and_composer_is_not_a_window_mixin(self):
        main_window = (
            PACKAGE_ROOT / "workbench" / "main_window.py"
        ).read_text(encoding="utf-8")
        bootstrap = (
            PACKAGE_ROOT / "workbench" / "bootstrap.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("def get_main_app(", main_window)
        self.assertNotIn("def main(", main_window)
        self.assertNotIn("WorkbenchCompositionMixin", main_window)
        self.assertNotIn("WorkbenchComposer", main_window)
        self.assertNotIn("@file_path.setter", main_window)
        self.assertIn("def create_workbench(", bootstrap)
        composer_importers = []
        for path in python_files(PACKAGE_ROOT):
            if "labelimg.workbench.composition" in set(imports(path)):
                composer_importers.append(package_relative_path(path))
        self.assertEqual(composer_importers, ["workbench/bootstrap.py"])

    def test_recovery_coordination_uses_public_feature_interfaces(self):
        recovery_ui = (
            PACKAGE_ROOT / "workbench" / "recovery_ui.py"
        )
        self.assertFalse(any(
            imported.startswith((
                "labelimg.files.",
                "labelimg.image_tools.",
            ))
            for imported in imports(recovery_ui)
        ))
        self.assertFalse(any(
            imported.startswith("labelimg.annotations")
            for imported in imports(PACKAGE_ROOT / "platform" / "recovery.py")
        ))
        composition_imports = set(imports(
            PACKAGE_ROOT / "workbench" / "composition.py"
        ))
        self.assertFalse(any(
            imported.startswith((
                "labelimg.files.application.transaction",
                "labelimg.files.application.recovery",
                "labelimg.image_tools.application.transaction",
                "labelimg.image_tools.application.recovery",
            ))
            for imported in composition_imports
        ))

    def test_file_list_projection_replaces_callback_compatibility_queries(self):
        list_widget = (
            PACKAGE_ROOT / "files" / "ui" / "list_widget.py"
        ).read_text(encoding="utf-8")
        for method in ("ordered_paths", "matches", "visible_paths"):
            self.assertNotIn("def %s(" % method, list_widget)

    def test_canvas_hover_is_observed_through_the_interaction_snapshot(self):
        canvas = (
            PACKAGE_ROOT / "canvas" / "widget.py"
        ).read_text(encoding="utf-8")
        for name in ("h_shape", "h_vertex", "h_edge"):
            self.assertNotIn("def %s(" % name, canvas)

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
