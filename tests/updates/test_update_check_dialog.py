import unittest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from labelimg.updates import (
    StableRelease,
    StableVersion,
    UpdateCenterWindow,
)


def release():
    version = StableVersion.parse("2.2.0")
    return StableRelease(
        version=version,
        tag_name="v2.2.0",
        name="LabelImg Enhanced 2.2.0",
        summary="Stable release",
        html_url="https://github.com/example/release",
        published_at="",
        wheel_url="https://github.com/example/package.whl",
        installer_url="https://github.com/example/setup.exe",
        sha256_url="https://github.com/example/SHA256SUMS",
    )


class UpdateCenterWindowTest(unittest.TestCase):
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

    def test_is_an_independent_minimizable_window(self):
        self.assertIsNone(self.center.parentWidget())
        self.assertTrue(self.center.isWindow())
        self.assertTrue(
            self.center.windowFlags() & Qt.WindowMinimizeButtonHint
        )
        self.assertFalse(self.center.isModal())

    def test_checking_is_cancelable_and_failure_is_retryable(self):
        canceled = []
        retried = []
        self.center.cancelCheckRequested.connect(
            lambda: canceled.append(True)
        )
        self.center.retryCheckRequested.connect(lambda: retried.append(True))

        self.center.show_checking()
        self.center.cancel_check_button.click()
        self.assertEqual(canceled, [True])

        self.center.show_check_failure("Connection closed")
        self.assertEqual(self.center.detail.text(), "Connection closed")
        self.center.retry_check_button.click()
        self.assertEqual(retried, [True])

    def test_downloading_close_hides_and_keeps_the_operation_alive(self):
        canceled = []
        self.center.cancelDownloadRequested.connect(
            lambda: canceled.append(True)
        )
        self.center.show_downloading(release())

        self.center.close()
        self.application.processEvents()

        self.assertFalse(self.center.isVisible())
        self.assertEqual(self.center.state, "downloading")
        self.assertEqual(canceled, [])

    def test_download_outcomes_have_explicit_recovery_actions(self):
        self.center.show_download_failure(release(), "HTTP 404")
        self.assertEqual(self.center.state, "download_failed")
        self.assertTrue(self.center.retry_download_button.isVisible())
        self.assertTrue(self.center.view_button.isVisible())

        self.center.show_download_canceled(release())
        self.assertEqual(self.center.state, "download_canceled")
        self.assertTrue(self.center.retry_download_button.isVisible())

        self.center.show_install_ready(release())
        self.assertEqual(self.center.state, "install_ready")
        self.assertTrue(self.center.install_button.isVisible())
        self.assertTrue(self.center.later_button.isVisible())
        self.assertTrue(self.center.view_button.isVisible())


if __name__ == "__main__":
    unittest.main()
