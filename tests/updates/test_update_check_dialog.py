import unittest

from PyQt5.QtWidgets import QApplication

from labelimg.updates import UpdateCheckDialog


class UpdateCheckDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = UpdateCheckDialog()
        self.dialog.show()
        self.application.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.application.processEvents()

    def test_checking_is_visible_non_modal_and_cancelable(self):
        canceled = []
        self.dialog.cancelRequested.connect(lambda: canceled.append(True))

        self.dialog.show_checking()

        self.assertFalse(self.dialog.isModal())
        self.assertTrue(self.dialog.progress.isVisible())
        self.assertTrue(self.dialog.cancel_button.isVisible())
        self.assertFalse(self.dialog.retry_button.isVisible())
        self.dialog.cancel_button.click()
        self.assertEqual(canceled, [True])

    def test_up_to_date_waits_for_explicit_close(self):
        self.dialog.show_up_to_date("2.1.0")

        self.assertTrue(self.dialog.isVisible())
        self.assertFalse(self.dialog.progress.isVisible())
        self.assertIn("2.1.0", self.dialog.heading.text())
        self.assertTrue(self.dialog.close_button.isVisible())
        self.assertFalse(self.dialog.retry_button.isVisible())

    def test_failure_shows_detail_and_offers_retry(self):
        retried = []
        self.dialog.retryRequested.connect(lambda: retried.append(True))

        self.dialog.show_failure("Connection closed")

        self.assertEqual(self.dialog.detail.text(), "Connection closed")
        self.assertTrue(self.dialog.retry_button.isVisible())
        self.dialog.retry_button.click()
        self.assertEqual(retried, [True])


if __name__ == "__main__":
    unittest.main()
