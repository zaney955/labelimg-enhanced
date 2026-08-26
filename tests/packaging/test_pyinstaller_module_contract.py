import importlib.util
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "labelimg"
HELPER = REPOSITORY_ROOT / "tools" / "pyinstaller_modules.py"
SPEC = REPOSITORY_ROOT / "packaging" / "labelimg-enhanced.spec"
ENTRY = REPOSITORY_ROOT / "src" / "labelimg" / "__main__.py"


def load_helper():
    module_spec = importlib.util.spec_from_file_location(
        "labelimg_pyinstaller_modules",
        HELPER,
    )
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


class PyInstallerModuleContractTest(unittest.TestCase):
    def test_local_module_inventory_includes_dynamic_export_targets(self):
        modules = set(load_helper().local_package_modules(PACKAGE_ROOT))

        self.assertIn("labelimg.annotations.application.session", modules)
        for initializer in PACKAGE_ROOT.rglob("__init__.py"):
            text = initializer.read_text(encoding="utf-8")
            for module_name in load_helper().dynamic_export_modules(text):
                self.assertIn(module_name, modules, initializer)

    def test_spec_uses_only_the_repository_local_module_inventory(self):
        content = SPEC.read_text(encoding="utf-8")

        self.assertIn("local_package_modules(package_root)", content)
        self.assertNotIn("collect_submodules", content)
        self.assertNotIn("hiddenimports=[]", content)

    def test_frozen_entry_has_a_noninteractive_import_smoke_gate(self):
        content = ENTRY.read_text(encoding="utf-8")

        self.assertIn("LABELIMG_PACKAGING_SMOKE_TEST", content)


if __name__ == "__main__":
    unittest.main()
