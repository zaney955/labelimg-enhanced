import unittest

from labelimg.annotations.infrastructure.storage import ResourceFingerprint
from labelimg.image_tools.application.recovery import (
    ImageRecoveryCenter,
    ImageRecoveryError,
)
from labelimg.platform.recovery import (
    RecoveryStatus,
    TrashIdentity,
    TrashedResource,
)


def resource(path):
    return TrashedResource(
        path,
        TrashIdentity("path", path + ".trash", path),
        ResourceFingerprint(True, size=10, modified_ns=20, sha256=path),
    )


class ImageProcessingRecoveryCenterTest(unittest.TestCase):
    def setUp(self):
        self.center = ImageRecoveryCenter()
        self.first = resource("first.jpg")
        self.second = resource("second.jpg")
        self.entry = self.center.record(
            (self.first, self.second)
        )

    def test_selected_subset_recovers_atomically_and_retains_the_rest(self):
        calls = []

        result = self.center.recover_resources(
            self.entry.entry_id,
            (self.first,),
            lambda _entry, selected: calls.append(selected) or "restored",
        )

        self.assertEqual(result, "restored")
        self.assertEqual(calls, [(self.first,)])
        self.assertEqual(self.entry.payload, (self.second,))
        self.assertEqual(self.entry.target_count, 1)
        self.assertEqual(self.entry.status, RecoveryStatus.RECOVERABLE)
        self.assertIn("1 image", self.entry.detail)

        self.center.recover_resources(
            self.entry.entry_id,
            (self.second,),
            lambda _entry, selected: selected,
        )
        self.assertEqual(self.entry.payload, ())
        self.assertEqual(self.entry.target_count, 0)
        self.assertEqual(self.entry.status, RecoveryStatus.RESTORED)

    def test_subset_must_be_nonempty_and_belong_to_the_entry(self):
        with self.assertRaises(ImageRecoveryError):
            self.center.recover_resources(
                self.entry.entry_id,
                (),
                lambda _entry, selected: selected,
            )
        with self.assertRaises(ImageRecoveryError):
            self.center.recover_resources(
                self.entry.entry_id,
                (resource("other.jpg"),),
                lambda _entry, selected: selected,
            )

    def test_failed_subset_recovery_keeps_every_resource_retryable(self):
        def fail(_entry, _selected):
            raise ImageRecoveryError("external change")

        with self.assertRaisesRegex(ImageRecoveryError, "external change"):
            self.center.recover_resources(
                self.entry.entry_id,
                (self.first,),
                fail,
            )

        self.assertEqual(self.entry.payload, (self.first, self.second))
        self.assertEqual(self.entry.status, RecoveryStatus.CONFLICT)
        self.assertTrue(self.entry.recoverable)

    def test_image_recovery_ledger_is_independent_and_clearable(self):
        self.assertEqual(self.center.entries, (self.entry,))
        self.center.clear()
        self.assertEqual(self.center.entries, ())


if __name__ == "__main__":
    unittest.main()
