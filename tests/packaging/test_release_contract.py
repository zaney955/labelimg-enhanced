import os
from pathlib import Path
import subprocess
import sys
import unittest

import labelimg


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPOSITORY_ROOT / "tools" / "validate_release.py"
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
INNO_SCRIPT = REPOSITORY_ROOT / "packaging" / "windows" / "labelimg-enhanced.iss"
PYINSTALLER_SPEC = REPOSITORY_ROOT / "packaging" / "labelimg-enhanced.spec"


class ReleaseContractTest(unittest.TestCase):
    def run_validator(self, tag):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
        return subprocess.run(
            [sys.executable, str(VALIDATOR), "--tag", tag],
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_release_validator_requires_tag_to_match_application_version(self):
        accepted = self.run_validator("v%s" % labelimg.__version__)
        rejected = self.run_validator("v99.99.99")

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("does not match", rejected.stderr)

    def test_release_workflow_builds_a_verified_draft_release(self):
        content = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("tags:", content)
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("RELEASE_TAG:", content)
        self.assertIn("git ls-remote --tags origin", content)
        self.assertIn("tools/validate_release.py", content)
        self.assertIn("git cat-file", content)
        self.assertIn("actions: read", content)
        self.assertIn("actions/workflows/ci.yml/runs", content)
        self.assertIn("head_branch -eq \"main\"", content)
        self.assertNotIn("tools/run_tests.py", content)
        self.assertIn("pip wheel", content)
        self.assertIn("attest-build-provenance", content)
        self.assertIn("gh release create", content)
        self.assertIn("--draft", content)
        self.assertIn("windows-latest", content)
        self.assertIn("python -m pyinstaller", content.casefold())
        self.assertIn("smoke_test_windows_bundle.py", content)
        self.assertIn("iscc", content.casefold())
        self.assertIn("SHA256SUMS", content)

    def test_windows_bundle_and_installer_are_explicitly_unsigned(self):
        spec = PYINSTALLER_SPEC.read_text(encoding="utf-8")
        installer = INNO_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("COLLECT(", spec)
        self.assertIn("third_party_licenses", spec)
        self.assertIn("managed-install.json", installer)
        self.assertIn("PrivilegesRequired=lowest", installer)
        self.assertIn("{localappdata}", installer)
        self.assertIn("Uninstallable=yes", installer)
        self.assertNotIn("SignTool=", installer)


if __name__ == "__main__":
    unittest.main()
