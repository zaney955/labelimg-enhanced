import unittest

from PyQt5.QtWidgets import QApplication

from labelimg.updates import (
    DistributionStrategy,
    StableRelease,
    StableVersion,
    UpdateCenterWindow,
)


def release():
    return StableRelease(
        version=StableVersion.parse("2.2.0"),
        tag_name="v2.2.0",
        name="LabelImg Enhanced 2.2.0",
        summary="",
        html_url="https://github.com/example/release",
        published_at="",
        wheel_url="https://github.com/example/package.whl",
        installer_url="https://github.com/example/setup.exe",
        sha256_url="https://github.com/example/SHA256SUMS",
    )


class UpdateCenterAvailabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.center = UpdateCenterWindow()
        self.center.show()
        self.application.processEvents()

    def tearDown(self):
        self.center.shutdown()
        self.application.processEvents()

    def test_managed_install_offers_installer_not_pip(self):
        self.center.show_available(
            release(), DistributionStrategy.MANAGED_WINDOWS
        )

        self.assertTrue(self.center.download_button.isVisible())
        self.assertEqual(
            self.center.download_button.text(), "Download and Install"
        )
        self.assertFalse(self.center.copy_button.isVisible())

    def test_python_install_keeps_explicit_pip_command(self):
        self.center.show_available(release(), DistributionStrategy.PYTHON)

        self.assertFalse(self.center.download_button.isVisible())
        self.assertTrue(self.center.copy_button.isVisible())

    def test_portable_build_does_not_claim_it_can_install(self):
        self.center.show_available(
            release(), DistributionStrategy.PORTABLE_FROZEN
        )

        self.assertFalse(self.center.download_button.isVisible())
        self.assertFalse(self.center.copy_button.isVisible())


if __name__ == "__main__":
    unittest.main()
