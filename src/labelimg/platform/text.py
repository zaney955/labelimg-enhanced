"""Normalize path and label text received from Qt APIs."""


def native_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value
