"""Qt-free image-directory discovery."""

from __future__ import annotations

import os
import re


_DIGITS = re.compile(r"(\d+)")


def _logical_key(value):
    parts = []
    for part in _DIGITS.split(str(value).casefold()):
        if not part:
            continue
        if part.isdigit():
            parts.append((0, int(part), -len(part), ""))
        else:
            parts.append((1, 0, 0, part))
    return tuple(parts)


def relative_image_sort_key(path, root):
    """Return a portable natural key with relative directories grouped."""
    absolute = os.path.abspath(os.fspath(path))
    relative = os.path.relpath(absolute, os.path.abspath(os.fspath(root)))
    parts = relative.replace("\\", "/").split("/")
    directories = tuple(_logical_key(part) for part in parts[:-1])
    filename = _logical_key(parts[-1] if parts else "")
    return directories, filename, absolute.casefold()


def discover_images(directory, extensions):
    """Discover supported images recursively in one stable natural order."""
    root = os.path.abspath(os.fspath(directory))
    supported = tuple(
        value.casefold() if str(value).startswith(".")
        else "." + str(value).casefold()
        for value in extensions
    )
    images = []
    for current, _directories, filenames in os.walk(root):
        for filename in filenames:
            if filename.casefold().endswith(supported):
                images.append(os.path.abspath(os.path.join(current, filename)))
    images.sort(key=lambda path: relative_image_sort_key(path, root))
    return tuple(images)
