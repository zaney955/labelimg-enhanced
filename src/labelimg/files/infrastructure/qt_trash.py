"""Thin Qt adapter for recycle-bin capability."""

from PyQt5.QtCore import QFile


def is_available():
    return hasattr(QFile, "moveToTrash")


def move_to_trash(path):
    return QFile.moveToTrash(path)
