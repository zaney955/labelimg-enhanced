"""Validate the current version's wheel when a build is available."""

import os
from pathlib import Path
import unittest
import zipfile

import labelimg


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WHEEL_PATH = Path(os.environ.get(
    "LABELIMG_TEST_WHEEL",
    REPOSITORY_ROOT / "dist" / (
        f"labelimg_enhanced-{labelimg.__version__}-py3-none-any.whl"
    ),
))


@unittest.skipUnless(
    "LABELIMG_TEST_WHEEL" in os.environ or WHEEL_PATH.is_file(),
    "build the current wheel or set LABELIMG_TEST_WHEEL before wheel-content checks",
)
class WheelContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = zipfile.ZipFile(WHEEL_PATH)
        cls.names = set(cls.archive.namelist())

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_root_package_is_not_repopulated_from_stale_build_output(self):
        root_modules = {
            name
            for name in self.names
            if name.startswith("labelimg/")
            and name.count("/") == 1
            and name.endswith(".py")
        }
        self.assertEqual(
            root_modules,
            {"labelimg/__init__.py", "labelimg/__main__.py"},
        )

    def test_console_entry_uses_workbench_bootstrap(self):
        entry_points = self.archive.read(
            f"labelimg_enhanced-{labelimg.__version__}.dist-info/entry_points.txt"
        ).decode("utf-8")
        self.assertIn(
            "labelImg = labelimg.workbench.bootstrap:main",
            entry_points,
        )

    def test_generated_qt_resources_are_packaged_at_the_new_path(self):
        self.assertIn("labelimg/ui/generated_resources.py", self.names)
        self.assertNotIn("labelimg/resources.py", self.names)

    def test_python_modules_match_the_current_source_tree(self):
        source_root = REPOSITORY_ROOT / "src"
        expected = {
            path.relative_to(source_root).as_posix()
            for path in (source_root / "labelimg").rglob("*.py")
        }
        packaged = {
            name for name in self.names
            if name.startswith("labelimg/") and name.endswith(".py")
        }
        self.assertEqual(packaged, expected)


class ContinuousIntegrationContractTest(unittest.TestCase):
    def test_ci_installs_the_project_dependency_contract(self):
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("python -m pip install .", workflow)

    def test_ci_shards_branch_pushes_and_bounds_each_test_file(self):
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("branches:", workflow)
        self.assertNotIn("tags:", workflow)
        self.assertIn("cancel-in-progress: true", workflow)
        self.assertIn("shard: [0, 1, 2, 3]", workflow)
        self.assertIn("--shard-index", workflow)
        self.assertIn("--shard-count 4", workflow)
        self.assertIn("--timeout-seconds 900", workflow)


if __name__ == "__main__":
    unittest.main()
