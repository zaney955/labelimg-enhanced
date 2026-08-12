"""Validate a locally built 2.0 wheel when one is present."""

from pathlib import Path
import unittest
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WHEELS = tuple(sorted((REPOSITORY_ROOT / "dist").glob(
    "labelimg_enhanced-2.0.0-*.whl"
)))


@unittest.skipUnless(WHEELS, "build the 2.0.0 wheel before wheel-content checks")
class WheelContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = zipfile.ZipFile(WHEELS[-1])
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
            "labelimg_enhanced-2.0.0.dist-info/entry_points.txt"
        ).decode("utf-8")
        self.assertIn(
            "labelImg = labelimg.workbench.bootstrap:main",
            entry_points,
        )

    def test_generated_qt_resources_are_packaged_at_the_new_path(self):
        self.assertIn("labelimg/ui/generated_resources.py", self.names)
        self.assertNotIn("labelimg/resources.py", self.names)


if __name__ == "__main__":
    unittest.main()
