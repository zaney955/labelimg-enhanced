"""Read-only category counts for the actual documents of workspace images."""

from collections import Counter
from dataclasses import dataclass
import math
import os
from pathlib import Path
from xml.etree import ElementTree

from labelimg.annotations.application.workspace import AnnotationWorkspace
from labelimg.annotations.domain.model import AnnotationDocumentError, YoloClassMappingError
from labelimg.annotations.infrastructure.formats.create_ml_collection import CreateMLAnnotationCollection
from labelimg.annotations.infrastructure.formats.yolo_classes import (
    missing_yolo_classes, resolve_yolo_classes, yolo_dataset_root,
)
from labelimg.annotations.infrastructure.storage import fingerprint_path


class StatisticsCanceled(Exception):
    pass


class StatisticsError(AnnotationDocumentError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CategoryCount:
    label: str
    boxes: int
    images: int


@dataclass(frozen=True)
class StatisticsIssue:
    image_path: str
    annotation_path: str
    error: object


@dataclass(frozen=True)
class AnnotationStatistics:
    categories: tuple
    total_images: int
    annotated_images: int
    empty_images: int
    missing_images: int
    unsaved_images: int
    issues: tuple

    @property
    def total_boxes(self):
        return sum(category.boxes for category in self.categories)


class AnnotationStatisticsCollector:
    """Count each image once, without decoding pixels or writing documents."""

    def __init__(self, workspace, editing):
        self.workspace = workspace
        self.editing = editing

    def collect(self, image_paths, progress=None):
        paths = tuple({os.path.normcase(os.path.abspath(path)): os.path.abspath(path) for path in image_paths}.values())
        indexed = AnnotationWorkspace(save_dir=self.workspace.save_dir, image_dir=self.workspace.image_dir)
        directory = self.workspace.save_dir or self.workspace.image_dir
        if directory:
            if not os.path.isdir(directory):
                raise StatisticsError("directory")
            def scan_error(error):
                raise error
            indexed.scan(directory, progress=(lambda: progress(0, 0)) if progress else None, onerror=scan_error)
        box_counts, image_counts = Counter(), Counter()
        issues = []
        annotated = empty = missing = unsaved = 0
        contents, collections, mappings = {}, {}, {}
        for position, image in enumerate(paths):
            if progress:
                progress(position, len(paths))
            target = ""
            try:
                view = self.editing.view_image(image, touch=False) if self.editing.has_image(image) else None
                if view is not None and view.dirty:
                    counts = Counter(box.label for box in view.snapshot.boxes)
                    unsaved += 1
                else:
                    target = (view.current_target if view else None) or self.workspace.active_document_path(image)
                    if not target or not os.path.isfile(target):
                        choices = indexed.document_choices(image)
                        if not choices:
                            missing += 1
                            continue
                        if len(choices) > 1:
                            target = "\n".join(choice.annotation_path for choice in choices)
                            raise StatisticsError("ambiguous")
                        target = choices[0].annotation_path
                    counts = self._read_counts(target, image, contents, collections, mappings)
                if any(not str(label).strip() for label in counts):
                    raise StatisticsError("invalid")
                box_counts.update(counts)
                image_counts.update(counts.keys())
                if counts:
                    annotated += 1
                else:
                    empty += 1
            except (OSError, ValueError, AnnotationDocumentError, ElementTree.ParseError) as error:
                issues.append(StatisticsIssue(image, target, error))
        if progress:
            progress(len(paths), len(paths))
        # A shared file/configuration must describe the same content throughout.
        for path, (_content, expected) in contents.items():
            if fingerprint_path(path) != expected:
                raise StatisticsError("changed")
        categories = tuple(CategoryCount(label, count, image_counts[label]) for label, count in sorted(box_counts.items(), key=lambda pair: (-pair[1], pair[0].casefold(), pair[0])))
        return AnnotationStatistics(categories, len(paths), annotated, empty, missing, unsaved, tuple(issues))

    @staticmethod
    def _content(path, cache):
        path = os.path.abspath(path)
        if path not in cache:
            expected = fingerprint_path(path)
            content = Path(path).read_bytes()
            if fingerprint_path(path) != expected:
                raise StatisticsError("changed")
            cache[path] = content, expected
        return cache[path][0]

    def _read_counts(self, target, image, contents, collections, mappings):
        content = self._content(target, contents)
        extension = Path(target).suffix.casefold()
        if extension == ".xml":
            root = ElementTree.fromstring(content)
            if root.tag != "annotation":
                raise StatisticsError("invalid")
            counts = Counter()
            for item in root.findall("object"):
                label = item.findtext("name", "")
                for field in ("xmin", "ymin", "xmax", "ymax"):
                    if not math.isfinite(float(item.findtext("bndbox/" + field, ""))):
                        raise StatisticsError("invalid")
                counts[label] += 1
            return counts
        if extension == ".json":
            if target not in collections:
                collections[target] = CreateMLAnnotationCollection.read(target, content=content, strict=True)
            record = collections[target].resolve(image)
            counts = Counter(record.labels)
            shapes = record.reader_shapes
            if sum(counts.values()) != len(shapes) or any(not math.isfinite(value) for _label, points, _difficult in shapes for point in points for value in point):
                raise StatisticsError("invalid")
            return counts
        if extension != ".txt" or Path(target).name.casefold() == "classes.txt":
            raise StatisticsError("invalid")
        rows = [(number, line.split()) for number, line in enumerate(content.decode("utf-8-sig").splitlines(), 1) if line.strip() and not line.lstrip().startswith("#")]
        if not rows:
            return Counter()
        directory = os.path.dirname(target)
        if directory not in mappings:
            def read_mapping(path):
                if not os.path.isfile(path):
                    contents.setdefault(os.path.abspath(path), (None, fingerprint_path(path)))
                    return None
                return self._content(path, contents)
            mapping = resolve_yolo_classes(target, allow_missing=True, dataset_root=yolo_dataset_root(target, self.workspace.save_dir or self.workspace.image_dir), read_content=read_mapping)
            self.workspace.confirm_class_mapping(mapping)
            mappings[directory] = mapping
        mapping = mappings[directory]
        counts = Counter()
        for line_number, fields in rows:
            if len(fields) != 5 or not all(math.isfinite(float(value)) for value in fields[1:]):
                raise StatisticsError("invalid")
            index = int(fields[0])
            if not mapping.names:
                raise missing_yolo_classes(target, mapping.resources, line_number=line_number)
            if not 0 <= index < len(mapping.names):
                raise YoloClassMappingError("out_of_range", target, line_number=line_number, class_index=index, class_count=len(mapping.names), class_list_path=mapping.source)
            counts[mapping.names[index]] += 1
        return counts
