"""Public image-processing contracts.

Submodules remain lazy so ordinary LabelImg startup does not load OpenCV.
"""

from importlib import import_module

__all__ = (
    "ImageProcessingOperation",
    "ImageProcessingSession",
    "ImageProcessingTransaction",
    "ImageRecoveryBlocked",
    "quality_finding_text",
)

_EXPORT_MODULES = {
    "ImageProcessingOperation": "labelimg.image_tools.application.recovery",
    "ImageProcessingSession": "labelimg.image_tools.application.session",
    "ImageProcessingTransaction": "labelimg.image_tools.application.transaction",
    "ImageRecoveryBlocked": "labelimg.image_tools.application.transaction",
    "quality_finding_text": "labelimg.image_tools.ui.quality_panel",
}


def __getattr__(name):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
