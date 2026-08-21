"""Qt-free file-list state, queries, and projections."""

from dataclasses import dataclass
from functools import cmp_to_key
import os
import re

from labelimg.files.application.discovery import relative_image_sort_key


def natural_sort(values, key=lambda value: value):
    """Sort a mutable sequence using case-insensitive numeric chunks."""

    def convert(text):
        return int(text) if text.isdigit() else text.casefold()

    values.sort(
        key=lambda value: [
            convert(part) for part in re.split(r"([0-9]+)", str(key(value)))
        ]
    )


def portable_logical_compare(left_name, right_name):
    """Compare text using case-insensitive natural numeric chunks."""
    left_parts = re.split(r"(\d+)", str(left_name).casefold())
    right_parts = re.split(r"(\d+)", str(right_name).casefold())
    for left_part, right_part in zip(left_parts, right_parts):
        left_is_number = left_part.isdigit()
        right_is_number = right_part.isdigit()
        if left_is_number and right_is_number:
            left_number = int(left_part)
            right_number = int(right_part)
            if left_number != right_number:
                return (left_number > right_number) - (
                    left_number < right_number
                )
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


def relative_path_parts(path, root):
    absolute = os.path.abspath(os.fspath(path))
    if root:
        try:
            relative = os.path.relpath(absolute, os.path.abspath(root))
        except ValueError:
            relative = os.path.basename(absolute)
    else:
        relative = os.path.basename(absolute)
    normalized = relative.replace("\\", "/")
    return tuple(part for part in normalized.split("/") if part)


def compare_relative_image_paths(left_path, right_path, root=None):
    """Keep relative directories grouped, then naturally order names."""
    left_parts = relative_path_parts(left_path, root)
    right_parts = relative_path_parts(right_path, root)
    left_dirs, left_name = left_parts[:-1], left_parts[-1:]
    right_dirs, right_name = right_parts[:-1], right_parts[-1:]
    for left_part, right_part in zip(left_dirs, right_dirs):
        comparison = portable_logical_compare(left_part, right_part)
        if comparison:
            return comparison
    if len(left_dirs) != len(right_dirs):
        return (len(left_dirs) > len(right_dirs)) - (
            len(left_dirs) < len(right_dirs)
        )
    comparison = portable_logical_compare(
        left_name[0] if left_name else "",
        right_name[0] if right_name else "",
    )
    if comparison:
        return comparison
    left_key = os.path.abspath(left_path).casefold()
    right_key = os.path.abspath(right_path).casefold()
    return (left_key > right_key) - (left_key < right_key)


@dataclass(frozen=True)
class FileListItemState:
    """Complete read-only state used to derive one file-list row."""

    path: str
    modified_time: float | None = None
    annotation_state: str = "unannotated"
    review_state: str = "unreviewed"
    persistence_flags: tuple = ()
    quality_findings: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "path", os.path.abspath(os.fspath(self.path)))
        object.__setattr__(
            self, "persistence_flags", tuple(self.persistence_flags or ())
        )
        object.__setattr__(
            self, "quality_findings", tuple(self.quality_findings or ())
        )


@dataclass(frozen=True)
class FileListQuery:
    """Sort and filter request for one file-list projection."""

    sort_key: str = "name"
    descending: bool = False
    text: str = ""
    annotation: str = "all"
    review: str = "all"
    alert: str = "all"
    quality: str = "all"

    SORT_KEYS = ("name", "modified", "annotation", "review")

    def __post_init__(self):
        if self.sort_key not in self.SORT_KEYS:
            object.__setattr__(self, "sort_key", "name")
        object.__setattr__(self, "descending", bool(self.descending))
        object.__setattr__(self, "text", str(self.text).strip())

    @property
    def filter_active(self):
        return bool(
            self.text
            or self.annotation != "all"
            or self.review != "all"
            or self.alert != "all"
            or self.quality != "all"
        )


@dataclass(frozen=True)
class FileListProjection:
    """One authoritative ordered and visible view of workspace images."""

    root: str | None
    query: FileListQuery
    items: tuple[FileListItemState, ...]
    ordered_paths: tuple[str, ...]
    visible_paths: tuple[str, ...]

    ANNOTATION_ORDER = {"unannotated": 0, "annotated": 1}
    REVIEW_ORDER = {"unreviewed": 0, "questioned": 1, "verified": 2}

    @classmethod
    def create(cls, root, items, query=None, presorted=False):
        query = query or FileListQuery()
        items = tuple(items)
        by_path = {item.path: item for item in items}
        if len(by_path) != len(items):
            raise ValueError("file-list projection paths must be unique")

        def path_compare(left, right):
            left_key = relative_image_sort_key(left, root or os.curdir)
            right_key = relative_image_sort_key(right, root or os.curdir)
            return (left_key > right_key) - (left_key < right_key)

        def primary(path):
            item = by_path[path]
            if query.sort_key == "annotation":
                return cls.ANNOTATION_ORDER.get(item.annotation_state, -1)
            if query.sort_key == "review":
                return cls.REVIEW_ORDER.get(item.review_state, -1)
            if query.sort_key == "modified":
                try:
                    return float(item.modified_time)
                except (TypeError, ValueError):
                    return float("-inf")
            return 0

        def compare(left, right):
            if query.sort_key == "name":
                comparison = path_compare(left, right)
                return -comparison if query.descending else comparison
            left_primary = primary(left)
            right_primary = primary(right)
            comparison = (left_primary > right_primary) - (
                left_primary < right_primary
            )
            if comparison:
                return -comparison if query.descending else comparison
            return path_compare(left, right)

        if presorted and query.sort_key == "name" and not query.descending:
            ordered = tuple(by_path)
        elif query.sort_key == "name":
            ordered = tuple(sorted(
                by_path,
                key=lambda path: relative_image_sort_key(
                    path, root or os.curdir
                ),
                reverse=query.descending,
            ))
        else:
            ordered = tuple(sorted(by_path, key=cmp_to_key(compare)))
        visible = tuple(
            path
            for path in ordered
            if cls._matches(by_path[path], root, query)
        )
        return cls(
            os.path.abspath(root) if root else None,
            query,
            items,
            ordered,
            visible,
        )

    @property
    def filter_active(self):
        return self.query.filter_active

    def adjacent_visible(self, current_path, direction):
        if not self.visible_paths:
            return None
        current_path = (
            os.path.abspath(os.fspath(current_path)) if current_path else None
        )
        if current_path not in self.ordered_paths:
            return self.visible_paths[0] if direction > 0 else None
        start = self.ordered_paths.index(current_path)
        indexes = (
            range(start + 1, len(self.ordered_paths))
            if direction > 0
            else range(start - 1, -1, -1)
        )
        visible = set(self.visible_paths)
        return next(
            (self.ordered_paths[index] for index in indexes
             if self.ordered_paths[index] in visible),
            None,
        )

    @staticmethod
    def _matches(item, root, query):
        if query.text:
            display_path = "/".join(
                relative_path_parts(item.path, root)
            ).casefold()
            normalized_query = query.text.replace("\\", "/").casefold()
            if normalized_query not in display_path:
                return False
        if (
            query.annotation != "all"
            and item.annotation_state != query.annotation
        ):
            return False
        if query.review != "all" and item.review_state != query.review:
            return False
        if query.alert == "any" and not item.persistence_flags:
            return False
        if query.alert == "none" and item.persistence_flags:
            return False
        quality = item.quality_findings
        if query.quality == "issues" and not quality:
            return False
        if query.quality == "passed" and quality:
            return False
        if query.quality in ("error", "warning") and not any(
            quality_finding_value(finding, "severity") == query.quality
            for finding in quality
        ):
            return False
        if query.quality not in (
            "all", "issues", "passed", "error", "warning"
        ) and not any(
            quality_finding_value(finding, "code") == query.quality
            for finding in quality
        ):
            return False
        return True


def quality_finding_value(finding, field):
    if isinstance(finding, dict):
        return finding.get(field)
    if hasattr(finding, field):
        return getattr(finding, field)
    return finding if field == "code" else None
