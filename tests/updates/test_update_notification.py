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

    def test_status_version_and_primary_action_are_separate(self):
        self.center.show_up_to_date("2.2.0")
        self.assertNotIn("2.2.0", self.center.heading.text())
        self.assertIn("2.2.0", self.center.version_label.text())
        self.assertFalse(self.center.current_version.isVisible())
        self.center.show_available(release(), DistributionStrategy.MANAGED_WINDOWS)
        self.assertTrue(self.center.current_version.isVisible())
        self.assertEqual(self.center.download_button.property("uiRole"), "primary")
        self.assertEqual(self.center.view_button.property("uiRole"), "updateLink")
        self.assertEqual(self.center.ignore_button.property("uiRole"), "updateLink")
        self.assertFalse(self.center.progress_row.isVisible())

    def test_failure_details_are_bounded_and_remain_verbatim(self):
        detail = "OS diagnostic " + "path/error " * 200
        self.center.show_check_failure(detail)
        self.application.processEvents()
        self.assertEqual(self.center.detail.text(), detail)
        self.assertTrue(self.center.detail_area.isVisible())
        self.assertLessEqual(self.center.detail_area.height(), 100)
        self.assertEqual(self.center.retry_check_button.property("uiRole"), "primary")
        self.center.show_checking()
        self.assertFalse(self.center.detail_area.isVisible())
        self.assertTrue(self.center.progress_row.isVisible())

    def test_language_and_theme_changes_preserve_download_state(self):
        from labelimg.localization.runtime import (
            set_language,
            ENGLISH,
            SIMPLIFIED_CHINESE,
        )
        from labelimg.ui.theme import appearance_theme, current_theme, set_theme

        before = current_theme().identifier
        try:
            self.center.show_downloading(release())
            self.center.set_download_progress(42, 100)
            set_language(SIMPLIFIED_CHINESE)
            set_theme(appearance_theme("dark", "rose").identifier)
            self.assertEqual(self.center.heading.text(), "正在下载更新…")
            self.assertEqual(self.center.progress.value(), 42)
            self.assertEqual(self.center.progress_caption.text(), "42%")
            self.assertTrue(self.center.cancel_download_button.isVisible())
            self.assertEqual(self.center.state, "downloading")
            self.center.show_install_ready(release())
            self.assertEqual(self.center.install_button.property("uiRole"), "primary")
        finally:
            set_theme(before)
            set_language(ENGLISH)

    def test_managed_install_offers_installer_not_pip(self):
        self.center.show_available(release(), DistributionStrategy.MANAGED_WINDOWS)

        self.assertTrue(self.center.download_button.isVisible())
        self.assertEqual(self.center.download_button.text(), "Download and Install")
        self.assertFalse(self.center.copy_button.isVisible())

    def test_python_install_keeps_explicit_pip_command(self):
        self.center.show_available(release(), DistributionStrategy.PYTHON)

        self.assertFalse(self.center.download_button.isVisible())
        self.assertTrue(self.center.copy_button.isVisible())

    def test_portable_build_does_not_claim_it_can_install(self):
        self.center.show_available(release(), DistributionStrategy.PORTABLE_FROZEN)

        self.assertFalse(self.center.download_button.isVisible())
        self.assertFalse(self.center.copy_button.isVisible())


if __name__ == "__main__":
    unittest.main()
