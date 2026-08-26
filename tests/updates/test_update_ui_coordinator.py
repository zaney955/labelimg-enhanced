import unittest

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget

from labelimg.updates import (
    DistributionStrategy,
    StableRelease,
    StableVersion,
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


def release(version):
    parsed = StableVersion.parse(version)
    return StableRelease(
        version=parsed,
        tag_name="v%s" % parsed,
        name="LabelImg Enhanced %s" % parsed,
        summary="Stable release",
        html_url="https://github.com/example/releases/tag/v%s" % parsed,
        published_at="2026-08-26T00:00:00Z",
        wheel_url=None,
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
        self.coordinator = UpdateUiCoordinator(
            self.window,
            FakeSettings(),
            "2.1.0",
            lambda message, delay: self.statuses.append((message, delay)),
            client=self.client,
            distribution_strategy=DistributionStrategy.PORTABLE_FROZEN,
        )
        self.application.processEvents()

    def tearDown(self):
        self.coordinator.close()
        self.window.close()
        self.application.processEvents()

    def test_manual_check_uses_one_visible_feedback_dialog(self):
        self.assertTrue(self.coordinator.check_manual())
        feedback = self.coordinator.check_dialog

        self.assertIsNotNone(feedback)
        self.assertTrue(feedback.isVisible())
        self.assertEqual(feedback.state, "checking")
        self.assertFalse(self.coordinator.check_manual())
        self.assertIs(self.coordinator.check_dialog, feedback)
        self.assertEqual(self.client.fetch_count, 1)

    def test_manual_up_to_date_result_stays_in_the_dialog(self):
        self.coordinator.check_manual()
        self.client.finish_success(release("2.1.0"))
        self.application.processEvents()

        feedback = self.coordinator.check_dialog
        self.assertEqual(feedback.state, "up_to_date")
        self.assertTrue(feedback.isVisible())
        self.assertIn("2.1.0", feedback.heading.text())

    def test_failure_can_retry_in_the_same_dialog(self):
        self.coordinator.check_manual()
        feedback = self.coordinator.check_dialog
        self.client.finish_failure("Connection closed")

        self.assertEqual(feedback.state, "failed")
        self.assertEqual(feedback.detail.text(), "Connection closed")
        feedback.retry_button.click()

        self.assertIs(self.coordinator.check_dialog, feedback)
        self.assertEqual(feedback.state, "checking")
        self.assertEqual(self.client.fetch_count, 2)

    def test_cancel_aborts_the_manual_check(self):
        self.coordinator.check_manual()
        self.coordinator.check_dialog.cancel_button.click()
        self.application.processEvents()

        self.assertEqual(self.client.cancel_count, 1)
        self.assertIsNone(self.coordinator.check_dialog)

    def test_new_release_replaces_feedback_with_update_notification(self):
        self.coordinator.check_manual()
        self.client.finish_success(release("2.2.0"))
        self.application.processEvents()

        self.assertIsNone(self.coordinator.check_dialog)
        self.assertIsNotNone(self.coordinator.dialog)
        self.assertTrue(self.coordinator.dialog.isVisible())

    def test_automatic_failure_has_no_feedback_dialog(self):
        self.assertTrue(self.coordinator.check_automatic())
        self.client.finish_failure("offline")
        self.application.processEvents()

        self.assertIsNone(self.coordinator.check_dialog)


if __name__ == "__main__":
    unittest.main()
