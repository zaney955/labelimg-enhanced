"""Windows Recycle Bin operations backed by IFileOperation."""

from ctypes import (
    POINTER,
    byref,
    c_int,
    c_uint,
    c_ulong,
    c_void_p,
    c_wchar_p,
)
import os
from functools import lru_cache
import uuid


CLSID_FILE_OPERATION = "{3AD05575-8857-4850-9277-11B85BDB8E09}"
IID_I_FILE_OPERATION = "{947AAB5F-0A5C-4C13-B4D6-4BF7836FC9F8}"
IID_I_FILE_OPERATION_PROGRESS_SINK = (
    "{04B0F1A7-9490-44BC-96E1-4296A31252E2}"
)
IID_I_SHELL_ITEM = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"

FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000
FOFX_RECYCLEONDELETE = 0x00080000
FOFX_ADDUNDORECORD = 0x20000000
SIGDN_FILESYSPATH = 0x80058000


class WindowsTrashError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _interfaces():
    from comtypes import (
        COMMETHOD,
        COMObject,
        GUID,
        HRESULT,
        IUnknown,
    )

    class IShellItem(IUnknown):
        _iid_ = GUID(IID_I_SHELL_ITEM)
        _methods_ = [
            COMMETHOD(
                [],
                HRESULT,
                "BindToHandler",
                (["in"], c_void_p, "pbc"),
                (["in"], POINTER(GUID), "bhid"),
                (["in"], POINTER(GUID), "riid"),
                (["out"], POINTER(c_void_p), "ppv"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "GetParent",
                (["out"], POINTER(c_void_p), "ppsi"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "GetDisplayName",
                (["in"], c_uint, "sigdnName"),
                (["out"], POINTER(c_wchar_p), "ppszName"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "GetAttributes",
                (["in"], c_uint, "sfgaoMask"),
                (["out"], POINTER(c_uint), "psfgaoAttribs"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "Compare",
                (["in"], c_void_p, "psi"),
                (["in"], c_uint, "hint"),
                (["out"], POINTER(c_int), "piOrder"),
            ),
        ]

    class IFileOperationProgressSink(IUnknown):
        _iid_ = GUID(IID_I_FILE_OPERATION_PROGRESS_SINK)
        _methods_ = [
            COMMETHOD([], HRESULT, "StartOperations"),
            COMMETHOD([], HRESULT, "FinishOperations", (["in"], HRESULT, "hrResult")),
            COMMETHOD([], HRESULT, "PreRenameItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "item"), (["in"], c_wchar_p, "name")),
            COMMETHOD([], HRESULT, "PostRenameItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "item"), (["in"], c_wchar_p, "name"), (["in"], HRESULT, "hr"), (["in"], c_void_p, "newItem")),
            COMMETHOD([], HRESULT, "PreMoveItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "item"), (["in"], c_void_p, "destination"), (["in"], c_wchar_p, "name")),
            COMMETHOD([], HRESULT, "PostMoveItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "item"), (["in"], c_void_p, "destination"), (["in"], c_wchar_p, "name"), (["in"], HRESULT, "hr"), (["in"], c_void_p, "newItem")),
            COMMETHOD([], HRESULT, "PreCopyItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "item"), (["in"], c_void_p, "destination"), (["in"], c_wchar_p, "name")),
            COMMETHOD([], HRESULT, "PostCopyItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "item"), (["in"], c_void_p, "destination"), (["in"], c_wchar_p, "name"), (["in"], HRESULT, "hr"), (["in"], c_void_p, "newItem")),
            COMMETHOD([], HRESULT, "PreDeleteItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "item")),
            COMMETHOD([], HRESULT, "PostDeleteItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "item"), (["in"], HRESULT, "hr"), (["in"], POINTER(IShellItem), "newItem")),
            COMMETHOD([], HRESULT, "PreNewItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "destination"), (["in"], c_wchar_p, "name")),
            COMMETHOD([], HRESULT, "PostNewItem", (["in"], c_uint, "flags"), (["in"], c_void_p, "destination"), (["in"], c_wchar_p, "name"), (["in"], c_wchar_p, "template"), (["in"], c_uint, "attributes"), (["in"], HRESULT, "hr"), (["in"], c_void_p, "newItem")),
            COMMETHOD([], HRESULT, "UpdateProgress", (["in"], c_uint, "total"), (["in"], c_uint, "completed")),
            COMMETHOD([], HRESULT, "ResetTimer"),
            COMMETHOD([], HRESULT, "PauseTimer"),
            COMMETHOD([], HRESULT, "ResumeTimer"),
        ]

    class IFileOperation(IUnknown):
        _iid_ = GUID(IID_I_FILE_OPERATION)
        _methods_ = [
            COMMETHOD([], HRESULT, "Advise", (["in"], POINTER(IFileOperationProgressSink), "sink"), (["out"], POINTER(c_ulong), "cookie")),
            COMMETHOD([], HRESULT, "Unadvise", (["in"], c_ulong, "cookie")),
            COMMETHOD([], HRESULT, "SetOperationFlags", (["in"], c_uint, "flags")),
            COMMETHOD([], HRESULT, "SetProgressMessage", (["in"], c_wchar_p, "message")),
            COMMETHOD([], HRESULT, "SetProgressDialog", (["in"], c_void_p, "dialog")),
            COMMETHOD([], HRESULT, "SetProperties", (["in"], c_void_p, "properties")),
            COMMETHOD([], HRESULT, "SetOwnerWindow", (["in"], c_void_p, "owner")),
            COMMETHOD([], HRESULT, "ApplyPropertiesToItem", (["in"], c_void_p, "item")),
            COMMETHOD([], HRESULT, "ApplyPropertiesToItems", (["in"], c_void_p, "items")),
            COMMETHOD([], HRESULT, "RenameItem", (["in"], c_void_p, "item"), (["in"], c_wchar_p, "name"), (["in"], c_void_p, "sink")),
            COMMETHOD([], HRESULT, "RenameItems", (["in"], c_void_p, "items"), (["in"], c_wchar_p, "name")),
            COMMETHOD([], HRESULT, "MoveItem", (["in"], POINTER(IShellItem), "item"), (["in"], POINTER(IShellItem), "destination"), (["in"], c_wchar_p, "name"), (["in"], c_void_p, "sink")),
            COMMETHOD([], HRESULT, "MoveItems", (["in"], c_void_p, "items"), (["in"], c_void_p, "destination")),
            COMMETHOD([], HRESULT, "CopyItem", (["in"], c_void_p, "item"), (["in"], c_void_p, "destination"), (["in"], c_wchar_p, "name"), (["in"], c_void_p, "sink")),
            COMMETHOD([], HRESULT, "CopyItems", (["in"], c_void_p, "items"), (["in"], c_void_p, "destination")),
            COMMETHOD([], HRESULT, "DeleteItem", (["in"], POINTER(IShellItem), "item"), (["in"], POINTER(IFileOperationProgressSink), "sink")),
            COMMETHOD([], HRESULT, "DeleteItems", (["in"], c_void_p, "items")),
            COMMETHOD([], HRESULT, "NewItem", (["in"], c_void_p, "destination"), (["in"], c_uint, "attributes"), (["in"], c_wchar_p, "name"), (["in"], c_wchar_p, "template"), (["in"], c_void_p, "sink")),
            COMMETHOD([], HRESULT, "PerformOperations"),
            COMMETHOD([], HRESULT, "GetAnyOperationsAborted", (["out"], POINTER(c_int), "aborted")),
        ]

    class ProgressSink(COMObject):
        _com_interfaces_ = [IFileOperationProgressSink]

        def __init__(self):
            super().__init__()
            self.deleted_item = None
            self.delete_hresult = None
            self.delete_flags = None
            self.delete_new_item_present = None
            self.delete_callbacks = []

        def StartOperations(self, this):
            return 0

        def FinishOperations(self, this, hrResult):
            return 0

        def PreRenameItem(self, this, *args):
            return 0

        def PostRenameItem(self, this, *args):
            return 0

        def PreMoveItem(self, this, *args):
            return 0

        def PostMoveItem(self, this, *args):
            return 0

        def PreCopyItem(self, this, *args):
            return 0

        def PostCopyItem(self, this, *args):
            return 0

        def PreDeleteItem(self, this, *args):
            return 0

        def PostDeleteItem(self, this, flags, item, hr, newItem):
            self.delete_flags = flags
            self.delete_hresult = hr
            self.delete_new_item_present = bool(newItem)
            self.delete_callbacks.append(
                (flags, hr, bool(newItem))
            )
            if newItem:
                self.deleted_item = _pidl_from_shell_item(newItem)
            return 0

        def PreNewItem(self, this, *args):
            return 0

        def PostNewItem(self, this, *args):
            return 0

        def UpdateProgress(self, this, *args):
            return 0

        def ResetTimer(self, this):
            return 0

        def PauseTimer(self, this):
            return 0

        def ResumeTimer(self, this):
            return 0

    return GUID, IShellItem, IFileOperation, ProgressSink


def _shell_item(path, guid_type, interface):
    import ctypes

    shell32 = ctypes.windll.shell32
    shell32.SHCreateItemFromParsingName.argtypes = (
        c_wchar_p,
        c_void_p,
        POINTER(guid_type),
        POINTER(POINTER(interface)),
    )
    shell32.SHCreateItemFromParsingName.restype = c_long = ctypes.c_long
    item = POINTER(interface)()
    result = shell32.SHCreateItemFromParsingName(
        os.path.abspath(path),
        None,
        byref(interface._iid_),
        byref(item),
    )
    if result < 0:
        raise WindowsTrashError(
            "SHCreateItemFromParsingName failed: 0x%08X"
            % (result & 0xFFFFFFFF)
        )
    return item


def _pidl_from_shell_item(item):
    """Copy an absolute PIDL while the callback-owned item is valid."""
    import ctypes

    shell32 = ctypes.windll.shell32
    shell32.SHGetIDListFromObject.argtypes = (
        c_void_p,
        POINTER(c_void_p),
    )
    shell32.SHGetIDListFromObject.restype = ctypes.c_long
    shell32.ILGetSize.argtypes = (c_void_p,)
    shell32.ILGetSize.restype = c_uint
    ctypes.windll.ole32.CoTaskMemFree.argtypes = (c_void_p,)
    ctypes.windll.ole32.CoTaskMemFree.restype = None
    pidl = c_void_p()
    result = shell32.SHGetIDListFromObject(item, byref(pidl))
    if result < 0 or not pidl.value:
        raise WindowsTrashError(
            "SHGetIDListFromObject failed: 0x%08X"
            % (result & 0xFFFFFFFF)
        )
    try:
        size = shell32.ILGetSize(pidl)
        if not size:
            raise WindowsTrashError(
                "The Recycle Bin item returned an empty PIDL."
            )
        return ctypes.string_at(pidl, size)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pidl)


def _shell_item_from_pidl(token, guid_type, interface):
    import ctypes

    if not isinstance(token, bytes) or not token:
        raise WindowsTrashError("The Recycle Bin identity is invalid.")
    shell32 = ctypes.windll.shell32
    shell32.SHCreateItemFromIDList.argtypes = (
        c_void_p,
        POINTER(guid_type),
        POINTER(POINTER(interface)),
    )
    shell32.SHCreateItemFromIDList.restype = ctypes.c_long
    buffer = ctypes.create_string_buffer(token)
    item = POINTER(interface)()
    result = shell32.SHCreateItemFromIDList(
        ctypes.cast(buffer, c_void_p),
        byref(interface._iid_),
        byref(item),
    )
    if result < 0:
        raise WindowsTrashError(
            "SHCreateItemFromIDList failed: 0x%08X"
            % (result & 0xFFFFFFFF)
        )
    return item


def _new_operation(interface):
    from comtypes import CLSCTX_INPROC_SERVER, CoCreateInstance, GUID

    operation = CoCreateInstance(
        GUID(CLSID_FILE_OPERATION),
        interface=interface,
        clsctx=CLSCTX_INPROC_SERVER,
    )
    operation.SetOperationFlags(
        FOFX_RECYCLEONDELETE
        | FOFX_ADDUNDORECORD
        | FOF_ALLOWUNDO
        | FOF_NOCONFIRMATION
        | FOF_SILENT
        | FOF_NOERRORUI
    )
    return operation


def delete_to_recycle_bin(path):
    path = os.path.abspath(os.fspath(path))
    if not os.path.isfile(path):
        raise WindowsTrashError(
            "Only regular files can be moved to the Recycle Bin."
        )
    probe_recycle_support(path)
    return _delete_to_recycle_bin_raw(path)


def probe_recycle_support(path):
    """Fail before touching user data when this path would be nuked."""
    directory = os.path.dirname(path)
    probe = os.path.join(
        directory,
        ".labelimg-recycle-probe-%s.tmp" % uuid.uuid4().hex,
    )
    try:
        with open(probe, "xb") as output:
            output.write(b"labelimg-recycle-probe")
        token = _delete_to_recycle_bin_raw(probe)
        restore_recycle_item(token, probe)
    except Exception as error:
        raise WindowsTrashError(
            "This location cannot provide a restorable Recycle Bin "
            "identity; the original file was not changed."
        ) from error
    finally:
        if os.path.exists(probe):
            os.remove(probe)


def recycle_item_exists(token):
    """Resolve the live Recycle Bin filesystem identity, not a cached COM pointer."""
    if token is None:
        return False
    try:
        GUID, IShellItem, _IFileOperation, _ProgressSink = _interfaces()
        item = _shell_item_from_pidl(token, GUID, IShellItem)
        path = item.GetDisplayName(SIGDN_FILESYSPATH)
    except Exception:
        return False
    return bool(path and os.path.lexists(os.fspath(path)))


def _delete_to_recycle_bin_raw(path):
    GUID, IShellItem, IFileOperation, ProgressSink = _interfaces()
    item = _shell_item(path, GUID, IShellItem)
    operation = _new_operation(IFileOperation)
    sink = ProgressSink()
    operation.DeleteItem(item, sink)
    operation.PerformOperations()
    aborted = operation.GetAnyOperationsAborted()
    if aborted or sink.deleted_item is None:
        raise WindowsTrashError(
            "Windows did not return a restorable Recycle Bin item "
            "(aborted=%r, callback_hresult=%r)."
            % (
                aborted,
                (
                    sink.delete_flags,
                    sink.delete_hresult,
                    sink.delete_new_item_present,
                    tuple(sink.delete_callbacks),
                ),
            )
        )
    return sink.deleted_item


def restore_recycle_item(token, destination):
    GUID, IShellItem, IFileOperation, _ProgressSink = _interfaces()
    parent_path = os.path.dirname(os.path.abspath(destination))
    name = os.path.basename(destination)
    parent = _shell_item(parent_path, GUID, IShellItem)
    item = _shell_item_from_pidl(token, GUID, IShellItem)
    operation = _new_operation(IFileOperation)
    operation.MoveItem(item, parent, name, None)
    operation.PerformOperations()
    aborted = operation.GetAnyOperationsAborted()
    if aborted or not os.path.lexists(destination):
        raise WindowsTrashError(
            "Windows could not restore the Recycle Bin item."
        )
