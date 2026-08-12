import unittest

from labelimg.annotations.infrastructure.storage import ResourceFingerprint
from labelimg.files.application.recovery import (
    FileRecoveryCenter,
    FileRecoveryError,
    RecoveryOperation,
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
        self.center = FileRecoveryCenter()
        self.first = resource("first.jpg")
        self.second = resource("second.jpg")
        self.entry = self.center.record_image_processing(
            (self.first, self.second)
        )

    def test_selected_subset_recovers_atomically_and_retains_the_rest(self):
        calls = []

        result = self.center.recover_subset(
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

        self.center.recover_subset(
            self.entry.entry_id,
            (self.second,),
            lambda _entry, selected: selected,
        )
        self.assertEqual(self.entry.payload, ())
        self.assertEqual(self.entry.target_count, 0)
        self.assertEqual(self.entry.status, RecoveryStatus.RESTORED)

    def test_subset_must_be_nonempty_and_belong_to_the_entry(self):
        with self.assertRaises(FileRecoveryError):
            self.center.recover_subset(
                self.entry.entry_id,
                (),
                lambda _entry, selected: selected,
            )
        with self.assertRaises(FileRecoveryError):
            self.center.recover_subset(
                self.entry.entry_id,
                (resource("other.jpg"),),
                lambda _entry, selected: selected,
            )

    def test_failed_subset_recovery_keeps_every_resource_retryable(self):
        def fail(_entry, _selected):
            raise FileRecoveryError("external change")

        with self.assertRaisesRegex(FileRecoveryError, "external change"):
            self.center.recover_subset(
                self.entry.entry_id,
                (self.first,),
                fail,
            )

        self.assertEqual(self.entry.payload, (self.first, self.second))
        self.assertEqual(self.entry.status, RecoveryStatus.CONFLICT)
        self.assertTrue(self.entry.recoverable)

    def test_full_recover_interface_remains_valid_for_other_operations(self):
        delete = self.center.record_trash_operation(
            RecoveryOperation.DELETE,
            (self.first,),
            target_count=1,
        )

        outcome = self.center.recover(
            delete.entry_id,
            lambda entry: entry.operation,
        )

        self.assertEqual(outcome, RecoveryOperation.DELETE)
        self.assertEqual(delete.status, RecoveryStatus.RESTORED)


if __name__ == "__main__":
    unittest.main()
