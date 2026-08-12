"""Qt-free annotation document values."""

from dataclasses import dataclass
from enum import Enum
import os


class AnnotationDocumentError(Exception):
    """An annotation document is invalid or cannot be interpreted."""


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
    line_color: tuple | None = None
    fill_color: tuple | None = None
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
        label, points, line_color, fill_color, difficult = reader_shape
        return cls(
            label=label,
            points=tuple(tuple(point) for point in points),
            line_color=line_color,
            fill_color=fill_color,
            difficult=bool(difficult),
        )

    def to_writer_shape(self):
        return {
            "label": self.label,
            "points": list(self.points),
            "line_color": self.line_color,
            "fill_color": self.fill_color,
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
