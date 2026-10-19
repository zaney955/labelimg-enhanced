"""Qt-free annotation document values."""

from dataclasses import dataclass
from enum import Enum
import os


class AnnotationDocumentError(Exception):
    """An annotation document is invalid or cannot be interpreted."""


class YoloClassMappingDeclined(AnnotationDocumentError):
    """The user cancelled loading an unusually located class mapping."""


class YoloWorkspaceMappingConflict(AnnotationDocumentError):
    def __init__(self, first_path, second_path, class_index, first_label, second_label):
        self.first_path = first_path
        self.second_path = second_path
        self.class_index = class_index
        self.first_label = first_label
        self.second_label = second_label
        super().__init__(
            "Inconsistent YOLO class ID %s: %s (%s) != %s (%s)"
            % (class_index, first_label, first_path, second_label, second_path)
        )


class YoloClassMappingError(AnnotationDocumentError):
    """Structured class diagnostics, localized by the workbench UI."""

    def __init__(
        self,
        reason,
        annotation_path,
        *,
        line_number=None,
        checked_paths=(),
        class_index=None,
        class_count=0,
        class_list_path=None,
    ):
        self.reason = reason
        self.annotation_path = os.fspath(annotation_path)
        self.line_number = line_number
        self.checked_paths = tuple(os.fspath(path) for path in checked_paths)
        self.class_index = class_index
        self.class_count = class_count
        self.class_list_path = class_list_path
        if reason == "missing":
            message = "Missing YOLO class mapping for %s. Checked: %s" % (
                self.annotation_path,
                ", ".join(self.checked_paths),
            )
        else:
            message = (
                "YOLO class ID %s at line %s is outside 0-%s. "
                "Mapping: %s (%s classes). Annotation: %s"
            ) % (
                class_index,
                line_number if line_number is not None else "?",
                class_count - 1,
                class_list_path,
                class_count,
                self.annotation_path,
            )
        super().__init__(message)


class AnnotationFormat(Enum):
    # Preserve values stored by historical LabelFileFormat settings.
    PASCAL_VOC = 1
    YOLO = 2
    CREATE_ML = 3

    @property
    def display_name(self):
        return {
            AnnotationFormat.PASCAL_VOC: "PascalVOC",
            AnnotationFormat.YOLO: "YOLO",
            AnnotationFormat.CREATE_ML: "CreateML",
        }[self]

    @property
    def extension(self):
        return {
            AnnotationFormat.PASCAL_VOC: ".xml",
            AnnotationFormat.YOLO: ".txt",
            AnnotationFormat.CREATE_ML: ".json",
        }[self]

    @classmethod
    def from_path(cls, path):
        extension = os.path.splitext(os.fspath(path))[1].lower()
        for annotation_format in cls:
            if annotation_format.extension == extension:
                return annotation_format
        raise AnnotationDocumentError(
            "Unsupported annotation format: %s" % extension
        )


@dataclass(frozen=True)
class AnnotationPoint:
    x: float
    y: float

    def as_tuple(self):
        return self.x, self.y


@dataclass(frozen=True)
class AnnotationBox:
    label: str
    points: tuple
    difficult: bool = False

    def __post_init__(self):
        object.__setattr__(
            self,
            "points",
            tuple(
                point.as_tuple()
                if isinstance(point, AnnotationPoint)
                else tuple(point)
                for point in self.points
            ),
        )

    @classmethod
    def from_reader_shape(cls, reader_shape):
        label, points, difficult = reader_shape
        return cls(
            label=label,
            points=tuple(tuple(point) for point in points),
            difficult=bool(difficult),
        )

    def to_writer_shape(self):
        return {
            "label": self.label,
            "points": list(self.points),
            "difficult": self.difficult,
        }


@dataclass(frozen=True)
class AnnotationStatus:
    has_annotations: bool
    verified: bool
    questioned: bool
    labels: frozenset


@dataclass
class AnnotationDocument:
    image_path: str
    image_data: object
    boxes: tuple = ()
    class_names: tuple = ()
    verified: bool = False
    questioned: bool = False
    create_ml_record_name: str | None = None

    @property
    def status(self):
        return AnnotationStatus(
            has_annotations=bool(self.boxes),
            verified=self.verified,
            questioned=self.questioned,
            labels=frozenset(box.label for box in self.boxes if box.label),
        )

    def toggle_verified(self):
        self.verified = not self.verified
        if self.verified:
            self.questioned = False

    def toggle_questioned(self):
        self.questioned = not self.questioned
        if self.questioned:
            self.verified = False
