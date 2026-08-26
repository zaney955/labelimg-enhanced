import unittest

from PyQt5.QtWidgets import QApplication

from labelimg.updates import (
    DistributionStrategy,
    StableRelease,
    StableVersion,
    UpdateNotificationDialog,
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


class UpdateNotificationDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_managed_install_offers_unsigned_installer_not_pip(self):
        dialog = UpdateNotificationDialog(
            release(),
            distribution_strategy=DistributionStrategy.MANAGED_WINDOWS,
        )

        self.assertIsNotNone(dialog.install_button)
        self.assertIsNone(dialog.copy_button)
        dialog.close()

    def test_python_install_keeps_explicit_pip_command(self):
        dialog = UpdateNotificationDialog(
            release(),
            distribution_strategy=DistributionStrategy.PYTHON,
        )

        self.assertIsNone(dialog.install_button)
        self.assertIsNotNone(dialog.copy_button)
        dialog.close()

    def test_portable_build_does_not_claim_it_can_install(self):
        dialog = UpdateNotificationDialog(
            release(),
            distribution_strategy=DistributionStrategy.PORTABLE_FROZEN,
        )

        self.assertIsNone(dialog.install_button)
        self.assertIsNone(dialog.copy_button)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
