import unittest

from PyQt5.QtCore import QObject, pyqtSignal

from labelimg.platform.settings_keys import (
    SETTING_AUTO_CHECK_UPDATES,
    SETTING_UPDATE_CACHED_RELEASE,
    SETTING_UPDATE_FAILURE_COUNT,
    SETTING_UPDATE_IGNORED_VERSION,
    SETTING_UPDATE_LAST_CHECKED_AT,
    SETTING_UPDATE_NEXT_CHECK_AT,
    SETTING_UPDATE_SNOOZED_UNTIL,
)
from labelimg.updates import StableRelease, StableVersion, UpdateController


class FakeSettings(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_count = 0

    def save(self):
        self.save_count += 1
        return True


class FakeReleaseClient(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.canceled = False

    def fetch(self):
        self.calls.append(True)
        return True

    def cancel(self):
        self.canceled = True


class BusyReleaseClient(FakeReleaseClient):
    def fetch(self):
        self.calls.append(True)
        return len(self.calls) == 1


def release(version="2.2.0"):
    parsed = StableVersion.parse(version)
    return StableRelease(
        version=parsed,
        tag_name="v%s" % parsed,
        name="LabelImg Enhanced %s" % parsed,
        summary="Stable release",
        html_url=(
            "https://github.com/zaney955/labelimg-enhanced/releases/tag/v%s"
            % parsed
        ),
        published_at="2026-08-26T00:00:00Z",
        wheel_url=None,
    )


class UpdateControllerTest(unittest.TestCase):
    def setUp(self):
        self.settings = FakeSettings({
            SETTING_AUTO_CHECK_UPDATES: True,
            SETTING_UPDATE_NEXT_CHECK_AT: 0,
        })
        self.client = FakeReleaseClient()
        self.controller = UpdateController(
            self.settings,
            current_version="2.1.0",
            client=self.client,
            clock=lambda: 1000,
        )

    def test_successful_automatic_check_caches_and_emits_new_release(self):
        available = []
        self.controller.updateAvailable.connect(available.append)

        self.assertTrue(self.controller.check(manual=False))
        self.client.succeeded.emit(release())

        self.assertEqual(available, [release()])
        self.assertEqual(self.settings[SETTING_UPDATE_LAST_CHECKED_AT], 1000)
        self.assertEqual(self.settings[SETTING_UPDATE_NEXT_CHECK_AT], 87400)
        self.assertEqual(self.settings[SETTING_UPDATE_FAILURE_COUNT], 0)
        self.assertEqual(
            self.settings[SETTING_UPDATE_CACHED_RELEASE]["tag_name"],
            "v2.2.0",
        )
        self.assertEqual(self.settings.save_count, 1)

    def test_automatic_failure_is_silent_but_manual_failure_is_visible(self):
        failures = []
        self.controller.checkFailed.connect(failures.append)

        self.controller.check(manual=False)
        self.client.failed.emit("offline")
        self.assertEqual(failures, [])

        self.controller.check(manual=True)
        self.client.failed.emit("offline")
        self.assertEqual(failures, ["offline"])
        self.assertEqual(self.settings[SETTING_UPDATE_FAILURE_COUNT], 2)

    def test_manual_check_bypasses_automatic_deadline(self):
        self.settings[SETTING_UPDATE_NEXT_CHECK_AT] = 9999

        self.assertFalse(self.controller.check(manual=False))
        self.assertTrue(self.controller.check(manual=True))

    def test_manual_check_promotes_an_in_flight_automatic_check(self):
        client = BusyReleaseClient()
        controller = UpdateController(
            self.settings,
            current_version="2.1.0",
            client=client,
            clock=lambda: 1000,
        )
        starts = []
        failures = []
        controller.checkStarted.connect(starts.append)
        controller.checkFailed.connect(failures.append)

        self.assertTrue(controller.check(manual=False))
        self.assertTrue(controller.check(manual=True))
        client.failed.emit("offline")

        self.assertEqual(starts, [False, True])
        self.assertEqual(failures, ["offline"])

    def test_manual_check_bypasses_a_snoozed_or_ignored_notice(self):
        available = []
        self.controller.updateAvailable.connect(available.append)
        self.settings[SETTING_UPDATE_IGNORED_VERSION] = "2.2.0"
        self.settings[SETTING_UPDATE_SNOOZED_UNTIL] = 9999

        self.controller.check(manual=True)
        self.client.succeeded.emit(release())

        self.assertEqual(available, [release()])

    def test_ignore_and_snooze_are_persisted(self):
        self.controller.ignore_version("2.2.0")
        self.controller.snooze()

        self.assertEqual(
            self.settings[SETTING_UPDATE_IGNORED_VERSION], "2.2.0"
        )
        self.assertEqual(
            self.settings[SETTING_UPDATE_SNOOZED_UNTIL], 87400
        )
        self.assertEqual(self.settings.save_count, 2)

    def test_close_cancels_the_transport(self):
        self.controller.close()

        self.assertTrue(self.client.canceled)


if __name__ == "__main__":
    unittest.main()
