import os
import tempfile
import unittest
from unittest import mock

from labelimg.windows_trash import (
    WindowsTrashError,
    delete_to_recycle_bin,
    recycle_item_exists,
)


class WindowsTrashSafetyTest(unittest.TestCase):
    def test_failed_probe_does_not_touch_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "image.png")
            with open(target, "wb") as output:
                output.write(b"image")

            def nuke_probe(path):
                os.remove(path)
                raise WindowsTrashError("no recycle identity")

            with mock.patch(
                "labelimg.windows_trash._delete_to_recycle_bin_raw",
                side_effect=nuke_probe,
            ):
                with self.assertRaises(WindowsTrashError):
                    delete_to_recycle_bin(target)

            self.assertTrue(os.path.isfile(target))
            with open(target, "rb") as source:
                self.assertEqual(source.read(), b"image")

    def test_stale_shell_item_is_not_reported_as_live(self):
        token = mock.Mock()
        token.GetDisplayName.side_effect = OSError("stale")

        self.assertFalse(recycle_item_exists(token))


if __name__ == "__main__":
    unittest.main()
