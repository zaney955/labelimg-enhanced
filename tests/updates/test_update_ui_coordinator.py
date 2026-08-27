import unittest
from unittest.mock import patch

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget

from labelimg.updates import (
    DistributionStrategy,
    StableRelease,
    StableVersion,
    UpdateCenterWindow,
    UpdateUiCoordinator,
)


class FakeSettings(dict):
    def save(self):
        return True


class FakeReleaseClient(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.busy = False
        self.fetch_count = 0
        self.cancel_count = 0

    def fetch(self):
        if self.busy:
            return False
        self.busy = True
        self.fetch_count += 1
        return True

    def cancel(self):
        self.busy = False
        self.cancel_count += 1

    def finish_success(self, value):
        self.busy = False
        self.succeeded.emit(value)

    def finish_failure(self, detail):
        self.busy = False
        self.failed.emit(detail)


class FakeDownloadClient(QObject):
    progress = pyqtSignal(int, int)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, _current_version):
        super().__init__()
        self.release = None
        self._candidate = None
        self.cancel_count = 0
        self.take_count = 0

    @property
    def candidate_path(self):
        return self._candidate

    def download(self, value):
        self.release = value
        return True

    def cancel(self):
        self.cancel_count += 1

    def finish_success(self, candidate="C:/Temp/update.exe"):
        self._candidate = candidate
        self.succeeded.emit(candidate)

    def finish_failure(self, detail):
        self.failed.emit(detail)

    def take_candidate(self):
        self.take_count += 1
        return self._candidate


class DownloadFactory:
    def __init__(self):
        self.instances = []

    def __call__(self, current_version, parent=None):
        client = FakeDownloadClient(current_version)
        client.setParent(parent)
        self.instances.append(client)
        return client


def release(version, managed=False):
    parsed = StableVersion.parse(version)
    root = "https://github.com/example/releases/download/v%s/" % parsed
    return StableRelease(
        version=parsed,
        tag_name="v%s" % parsed,
        name="LabelImg Enhanced %s" % parsed,
        summary="Stable release",
        html_url="https://github.com/example/releases/tag/v%s" % parsed,
        published_at="2026-08-26T00:00:00Z",
        wheel_url=None,
        installer_url=(root + "setup.exe") if managed else None,
        sha256_url=(root + "SHA256SUMS") if managed else None,
    )


class UpdateUiCoordinatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.window.show()
        self.client = FakeReleaseClient()
        self.statuses = []
        self.download_factory = DownloadFactory()
        self.coordinator = UpdateUiCoordinator(
            self.window,
            FakeSettings(),
            "2.1.0",
            lambda message, delay: self.statuses.append((message, delay)),
            client=self.client,
            distribution_strategy=DistributionStrategy.PORTABLE_FROZEN,
            download_client_factory=self.download_factory,
        )
        self.application.processEvents()

    def tearDown(self):
        self.coordinator.close()
        self.window.close()
        self.application.processEvents()

    def _use_managed_install(self):
        self.coordinator.distribution_strategy = (
            DistributionStrategy.MANAGED_WINDOWS
        )
        value = release("2.2.0", managed=True)
        self.coordinator._show_available(value)
        return value

    def test_manual_check_uses_one_independent_update_center(self):
        self.assertTrue(self.coordinator.check_manual())
        center = self.coordinator.center

        self.assertIsInstance(center, UpdateCenterWindow)
        self.assertIsNone(center.parentWidget())
        self.assertTrue(center.isVisible())
        self.assertEqual(center.state, "checking")
        self.assertFalse(self.coordinator.check_manual())
        self.assertIs(self.coordinator.center, center)
        self.assertEqual(self.client.fetch_count, 1)

    def test_manual_results_stay_in_the_same_center(self):
        self.coordinator.check_manual()
        center = self.coordinator.center
        self.client.finish_success(release("2.1.0"))
        self.application.processEvents()

        self.assertIs(self.coordinator.center, center)
        self.assertEqual(center.state, "up_to_date")
        self.assertIn("2.1.0", center.heading.text())

        self.coordinator.check_manual()
        self.client.finish_failure("Connection closed")
        self.assertEqual(center.state, "check_failed")
        center.retry_check_button.click()
        self.assertEqual(center.state, "checking")
        self.assertEqual(self.client.fetch_count, 3)

    def test_cancel_check_closes_the_center(self):
        self.coordinator.check_manual()
        self.coordinator.center.cancel_check_button.click()
        self.application.processEvents()

        self.assertEqual(self.client.cancel_count, 1)
        self.assertIsNone(self.coordinator.center)

    def test_new_release_reuses_the_check_center(self):
        self.coordinator.check_manual()
        center = self.coordinator.center
        self.client.finish_success(release("2.2.0"))
        self.application.processEvents()

        self.assertIs(self.coordinator.center, center)
        self.assertEqual(center.state, "available")

    def test_automatic_failure_is_silent(self):
        self.assertTrue(self.coordinator.check_automatic())
        self.client.finish_failure("offline")
        self.application.processEvents()

        self.assertIsNone(self.coordinator.center)

    def test_automatic_availability_requests_attention_without_activation(self):
        with (
            patch.object(QApplication, "alert") as alert,
            patch.object(UpdateCenterWindow, "activateWindow") as activate,
        ):
            self.coordinator.check_automatic()
            self.client.finish_success(release("2.2.0"))
            self.application.processEvents()

        alert.assert_called_once_with(self.coordinator.center, 0)
        activate.assert_not_called()

    def test_download_continues_when_the_center_is_closed(self):
        self._use_managed_install()
        self.coordinator.center.download_button.click()
        download = self.download_factory.instances[-1]

        self.coordinator.center.close()
        self.application.processEvents()

        self.assertFalse(self.coordinator.center.isVisible())
        self.assertIs(self.coordinator.download_client, download)
        self.assertEqual(download.cancel_count, 0)

    def test_download_failure_and_completion_request_attention(self):
        value = self._use_managed_install()
        self.coordinator.center.download_button.click()
        failed_download = self.download_factory.instances[-1]
        self.coordinator.center.hide()

        with patch.object(QApplication, "alert") as alert:
            failed_download.finish_failure("GitHub returned HTTP 404")
            self.application.processEvents()

        self.assertEqual(self.coordinator.center.state, "download_failed")
        self.assertTrue(self.coordinator.center.isVisible())
        self.assertIsNone(self.coordinator.download_client)
        alert.assert_called_once_with(self.coordinator.center, 0)

        self.coordinator.center.retry_download_button.click()
        ready_download = self.download_factory.instances[-1]
        self.coordinator.center.hide()
        with patch.object(QApplication, "alert") as alert:
            ready_download.finish_success()
            self.application.processEvents()

        self.assertEqual(self.coordinator.center.state, "install_ready")
        self.assertTrue(self.coordinator.center.isVisible())
        self.assertIs(self.coordinator.download_client, ready_download)
        self.assertEqual(ready_download.release, value)
        alert.assert_called_once_with(self.coordinator.center, 0)

    def test_cancel_download_keeps_a_restartable_state(self):
        self._use_managed_install()
        self.coordinator.center.download_button.click()
        download = self.download_factory.instances[-1]

        self.coordinator.center.cancel_download_button.click()
        self.application.processEvents()

        self.assertEqual(download.cancel_count, 1)
        self.assertEqual(self.coordinator.center.state, "download_canceled")
        self.assertTrue(self.coordinator.center.retry_download_button.isVisible())
        self.assertIsNone(self.coordinator.download_client)

    def test_ready_candidate_survives_center_close_and_reopens_without_check(self):
        self._use_managed_install()
        self.coordinator.center.download_button.click()
        download = self.download_factory.instances[-1]
        download.finish_success()
        self.coordinator.center.close()
        self.application.processEvents()

        self.assertIsNone(self.coordinator.center)
        self.assertIs(self.coordinator.download_client, download)
        self.assertFalse(self.coordinator.check_manual())
        self.assertEqual(self.coordinator.center.state, "install_ready")
        self.assertEqual(self.client.fetch_count, 0)

    def test_install_now_launches_without_an_intermediate_confirmation(self):
        self._use_managed_install()
        self.coordinator.center.download_button.click()
        download = self.download_factory.instances[-1]
        download.finish_success()
        original_close = self.window.close

        def close_and_cleanup():
            self.coordinator.close()
            return original_close()

        launched = []
        with (
            patch.object(self.window, "close", close_and_cleanup),
            patch(
                "labelimg.updates.ui.controller.QProcess.startDetached",
                side_effect=lambda path, arguments: launched.append(
                    (path, arguments)
                ) or True,
            ),
        ):
            self.coordinator.center.install_button.click()

        self.assertEqual(launched, [("C:/Temp/update.exe", [])])
        self.assertEqual(download.take_count, 1)


if __name__ == "__main__":
    unittest.main()
