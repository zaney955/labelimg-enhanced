"""Small stateless helpers used by workbench coordinators."""

from PyQt5.QtGui import QImageReader


APP_NAME = "labelImg"


def document_format_name(annotation_format):
    return annotation_format.display_name


def read_image(filename, default=None):
    try:
        reader = QImageReader(filename)
        reader.setAutoTransform(True)
        return reader.read()
    except Exception:
        return default
