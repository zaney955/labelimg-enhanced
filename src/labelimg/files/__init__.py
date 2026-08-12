"""Public contracts for file operations and recovery."""

from importlib import import_module

__all__ = (
    "FileOperationTransaction",
    "FileOperationBlocked",
    "FileListItemState",
    "FileListProjection",
    "FileListQuery",
    "FileRecoveryBlocked",
    "RecoveryOperation",
    "SystemTrashAdapter",
)

_EXPORT_MODULES = {
    "FileOperationTransaction": "labelimg.files.application.transaction",
    "FileOperationBlocked": "labelimg.files.application.transaction",
    "FileListItemState": "labelimg.files.model",
    "FileListProjection": "labelimg.files.model",
    "FileListQuery": "labelimg.files.model",
    "FileRecoveryBlocked": "labelimg.files.application.transaction",
    "RecoveryOperation": "labelimg.files.application.recovery",
    "SystemTrashAdapter": "labelimg.files.application.operations",
}


def __getattr__(name):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
