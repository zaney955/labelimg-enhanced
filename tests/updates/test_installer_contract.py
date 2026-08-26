from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from labelimg.updates import (
    installer_asset_name,
    parse_sha256_manifest,
    sha256_matches,
)


class InstallerContractTest(unittest.TestCase):
    def test_installer_asset_name_is_versioned_and_stable(self):
        self.assertEqual(
            installer_asset_name("2.2.0"),
            "LabelImg-Enhanced-2.2.0-windows-x64-setup.exe",
        )

    def test_manifest_selects_exact_installer_entry(self):
        name = installer_asset_name("2.2.0")
        digest = "ab" * 32
        manifest = "%s  other.whl\n%s *%s\n" % (
            "cd" * 32,
            digest,
            name,
        )

        self.assertEqual(parse_sha256_manifest(manifest, name), digest)

    def test_manifest_rejects_missing_duplicate_or_malformed_entry(self):
        name = installer_asset_name("2.2.0")
        digest = "ab" * 32
        invalid = (
            "",
            "not-a-digest *%s\n" % name,
            "%s *%s\n%s  %s\n" % (digest, name, digest, name),
        )
        for manifest in invalid:
            with self.subTest(manifest=manifest):
                with self.assertRaises(ValueError):
                    parse_sha256_manifest(manifest, name)

    def test_candidate_must_match_the_published_sha256(self):
        with TemporaryDirectory() as directory:
            candidate = Path(directory) / "setup.exe"
            candidate.write_bytes(b"installer")
            expected = sha256(b"installer").hexdigest()

            self.assertTrue(sha256_matches(candidate, expected))
            self.assertFalse(sha256_matches(candidate, "00" * 32))


if __name__ == "__main__":
    unittest.main()
