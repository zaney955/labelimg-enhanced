import os
import tempfile
import unittest
from unittest import mock

from labelimg.platform.trash import (
    FOF_ALLOWUNDO,
    FOFX_ADDUNDORECORD,
    FOFX_RECYCLEONDELETE,
    WindowsTrashError,
    _new_operation,
    _delete_to_recycle_bin_raw,
    _interfaces,
    delete_to_recycle_bin,
    recycle_item_exists,
)


class WindowsTrashSafetyTest(unittest.TestCase):
    def test_operation_flags_request_recycle_and_undo_identity(self):
        operation = mock.Mock()
        with mock.patch(
            "comtypes.CoCreateInstance", return_value=operation
        ):
            self.assertIs(_new_operation(mock.sentinel.interface), operation)

        flags = operation.SetOperationFlags.call_args.args[0]
        self.assertTrue(flags & FOFX_RECYCLEONDELETE)
        self.assertTrue(flags & FOF_ALLOWUNDO)
        self.assertTrue(flags & FOFX_ADDUNDORECORD)

    def test_progress_callback_copies_pidl_before_item_expires(self):
        _guid, _item, _operation, progress_sink = _interfaces()
        sink = progress_sink()
        callback_item = mock.Mock()
        with mock.patch(
            "labelimg.platform.trash._pidl_from_shell_item",
            return_value=b"copied-pidl",
        ) as copy_pidl:
            sink.PostDeleteItem(
                None,
                0x202,
                mock.sentinel.original,
                0x00270008,
                callback_item,
            )

        copy_pidl.assert_called_once_with(callback_item)
        self.assertEqual(sink.deleted_item, b"copied-pidl")

    def test_shell_success_code_is_accepted_with_copied_identity(self):
        class FakeSink:
            def __init__(self):
                self.deleted_item = b"pidl"
                self.delete_flags = 0x202
                self.delete_hresult = 0x00270008
                self.delete_new_item_present = True
                self.delete_callbacks = [
                    (0x202, 0x00270008, True)
                ]

        operation = mock.Mock()
        operation.GetAnyOperationsAborted.return_value = 0
        with mock.patch(
            "labelimg.platform.trash._interfaces",
            return_value=(
                mock.sentinel.guid,
                mock.sentinel.item_interface,
                mock.sentinel.operation_interface,
                FakeSink,
            ),
        ), mock.patch(
            "labelimg.platform.trash._shell_item",
            return_value=mock.sentinel.item,
        ), mock.patch(
            "labelimg.platform.trash._new_operation",
            return_value=operation,
        ):
            token = _delete_to_recycle_bin_raw("image.png")

        self.assertEqual(token, b"pidl")

    def test_failed_probe_does_not_touch_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "image.png")
            with open(target, "wb") as output:
                output.write(b"image")

            def nuke_probe(path):
                os.remove(path)
                raise WindowsTrashError("no recycle identity")

            with mock.patch(
                "labelimg.platform.trash._delete_to_recycle_bin_raw",
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
