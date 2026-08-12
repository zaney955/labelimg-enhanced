"""Qt-free file-list value helpers."""

import re


def natural_sort(values, key=lambda value: value):
    def convert(text):
        return int(text) if text.isdigit() else text

    values.sort(
        key=lambda value: [
            convert(part) for part in re.split(r"([0-9]+)", key(value))
        ]
    )
