"""Small stateless helpers used by workbench coordinators."""

import ctypes
import os
import platform
import re

from PyQt5.QtGui import QColor, QImageReader

from labelimg.annotations.domain.model import AnnotationFormat


APP_NAME = "labelImg"


def document_format_name(annotation_format):
    return annotation_format.display_name


if platform.system() == "Windows":
    WINDOWS_LOGICAL_COMPARE = ctypes.windll.shlwapi.StrCmpLogicalW
    WINDOWS_LOGICAL_COMPARE.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    WINDOWS_LOGICAL_COMPARE.restype = ctypes.c_int
else:
    WINDOWS_LOGICAL_COMPARE = None


def portable_logical_compare(left_name, right_name):
    left_parts = re.split(r"(\d+)", left_name.casefold())
    right_parts = re.split(r"(\d+)", right_name.casefold())
    for left_part, right_part in zip(left_parts, right_parts):
        left_is_number = left_part.isdigit()
        right_is_number = right_part.isdigit()
        if left_is_number and right_is_number:
            left_number = int(left_part)
            right_number = int(right_part)
            if left_number != right_number:
                return (left_number > right_number) - (left_number < right_number)
            if len(left_part) != len(right_part):
                return (len(right_part) > len(left_part)) - (
                    len(right_part) < len(left_part)
                )
        elif left_is_number != right_is_number:
            return -1 if left_is_number else 1
        elif left_part != right_part:
            return (left_part > right_part) - (left_part < right_part)
    return (len(left_parts) > len(right_parts)) - (
        len(left_parts) < len(right_parts)
    )


def compare_image_paths(left_path, right_path):
    left_name = os.path.basename(left_path)
    right_name = os.path.basename(right_path)
    comparison = (
        WINDOWS_LOGICAL_COMPARE(left_name, right_name)
        if WINDOWS_LOGICAL_COMPARE is not None
        else portable_logical_compare(left_name, right_name)
    )
    if comparison:
        return comparison
    left_key = left_path.casefold()
    right_key = right_path.casefold()
    return (left_key > right_key) - (left_key < right_key)


def inverted(color):
    return QColor(*[255 - value for value in color.getRgb()])


def read_image(filename, default=None):
    try:
        reader = QImageReader(filename)
        reader.setAutoTransform(True)
        return reader.read()
    except Exception:
        return default
