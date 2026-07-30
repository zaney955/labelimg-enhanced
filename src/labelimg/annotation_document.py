"""One image's annotation document and its storage adapters."""

from dataclasses import dataclass
from enum import Enum
import json
import math
import os
from xml.etree import ElementTree

try:
    from PyQt5.QtGui import QColor, QImage
    from PyQt5.QtCore import QPointF
except ImportError:
    from PyQt4.QtGui import QColor, QImage
    from PyQt4.QtCore import QPointF

from labelimg.create_ml_io import CreateMLReader, CreateMLWriter, JSON_EXT
from labelimg.pascal_voc_io import PascalVocReader, PascalVocWriter, XML_EXT
from labelimg.shape import Shape
from labelimg.yolo_io import TXT_EXT, YOLOWriter, YoloReader


class AnnotationFormat(Enum):
    # Preserve the values used by the legacy LabelFileFormat enum so existing
    # pickled user settings can be migrated by the restricted unpickler.
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
            AnnotationFormat.PASCAL_VOC: XML_EXT,
            AnnotationFormat.YOLO: TXT_EXT,
            AnnotationFormat.CREATE_ML: JSON_EXT,
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


class AnnotationDocumentError(Exception):
    pass


@dataclass(frozen=True)
class AnnotationBox:
    label: str
    points: tuple
    line_color: tuple | None = None
    fill_color: tuple | None = None
    difficult: bool = False

    @classmethod
    def from_shape(cls, shape):
        return cls(
            label=shape.label,
            points=tuple((point.x(), point.y()) for point in shape.points),
            line_color=(
                shape.line_color.getRgb()
                if shape.line_color is not None
                else None
            ),
            fill_color=(
                shape.fill_color.getRgb()
                if shape.fill_color is not None
                else None
            ),
            difficult=bool(shape.difficult),
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

    def to_shape(self, snap_point, color_for_label):
        shape = Shape(label=self.label)
        snapped_any = False
        for x, y in self.points:
            x, y, snapped = snap_point(x, y)
            snapped_any = snapped_any or snapped
            shape.add_point(QPointF(x, y))
        shape.difficult = self.difficult
        shape.close()
        shape.line_color = (
            QColor(*self.line_color)
            if self.line_color
            else color_for_label(self.label)
        )
        shape.fill_color = (
            QColor(*self.fill_color)
            if self.fill_color
            else color_for_label(self.label)
        )
        return shape, snapped_any


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

    @classmethod
    def from_shapes(
        cls,
        image_path,
        image_data,
        shapes,
        class_names=(),
        verified=False,
        questioned=False,
    ):
        return cls(
            image_path=os.fspath(image_path),
            image_data=image_data,
            boxes=tuple(AnnotationBox.from_shape(shape) for shape in shapes),
            class_names=tuple(class_names),
            verified=bool(verified),
            questioned=bool(questioned),
        )

    @classmethod
    def load(cls, annotation_path, image_path, image_data):
        annotation_format = AnnotationFormat.from_path(annotation_path)
        try:
            if annotation_format is AnnotationFormat.PASCAL_VOC:
                reader = PascalVocReader(os.fspath(annotation_path))
            elif annotation_format is AnnotationFormat.YOLO:
                reader = YoloReader(
                    os.fspath(annotation_path),
                    _as_qimage(image_path, image_data),
                )
            else:
                reader = CreateMLReader(
                    os.fspath(annotation_path),
                    os.fspath(image_path),
                )
        except Exception as error:
            raise AnnotationDocumentError(str(error)) from error

        return cls(
            image_path=os.fspath(image_path),
            image_data=image_data,
            boxes=tuple(
                AnnotationBox.from_reader_shape(shape)
                for shape in reader.get_shapes()
            ),
            class_names=tuple(
                _labels_in_order(
                    shape[0] for shape in reader.get_shapes()
                )
            ),
            verified=bool(reader.verified),
            questioned=bool(reader.questioned),
        )

    @classmethod
    def image_path_hint(cls, annotation_path):
        """Return an image path named by an annotation document, if any."""
        annotation_path = os.path.abspath(os.fspath(annotation_path))
        annotation_format = AnnotationFormat.from_path(annotation_path)
        directory = os.path.dirname(annotation_path)
        try:
            if annotation_format is AnnotationFormat.PASCAL_VOC:
                root = ElementTree.parse(annotation_path).getroot()
                path_text = root.findtext("path")
                filename = root.findtext("filename")
                candidates = (path_text, filename)
            elif annotation_format is AnnotationFormat.CREATE_ML:
                with open(
                    annotation_path,
                    "r",
                    encoding="utf8",
                ) as annotation_file:
                    images = json.load(annotation_file)
                candidates = tuple(
                    image.get("image")
                    for image in images
                    if image.get("image")
                )
            else:
                candidates = ()
        except (OSError, ValueError, ElementTree.ParseError):
            return None

        for candidate in candidates:
            if not candidate:
                continue
            candidate = os.fspath(candidate)
            if not os.path.isabs(candidate):
                candidate = os.path.join(directory, candidate)
            candidate = os.path.abspath(candidate)
            if os.path.isfile(candidate):
                return candidate
        return None

    @classmethod
    def inspect(cls, annotation_path, image_path=None, image_data=None):
        annotation_format = AnnotationFormat.from_path(annotation_path)
        try:
            if annotation_format is AnnotationFormat.PASCAL_VOC:
                reader = PascalVocReader(os.fspath(annotation_path))
                boxes = tuple(
                    AnnotationBox.from_reader_shape(shape)
                    for shape in reader.get_shapes()
                )
                return AnnotationStatus(
                    has_annotations=bool(boxes),
                    verified=bool(reader.verified),
                    questioned=bool(reader.questioned),
                    labels=frozenset(
                        box.label for box in boxes if box.label
                    ),
                )
            if annotation_format is AnnotationFormat.YOLO and image_data is None:
                labels, has_annotations = _inspect_yolo(annotation_path)
                return AnnotationStatus(
                    has_annotations=has_annotations,
                    verified=False,
                    questioned=False,
                    labels=frozenset(labels),
                )
            if annotation_format is AnnotationFormat.CREATE_ML and image_path is None:
                labels, has_annotations = _inspect_create_ml(annotation_path)
                return AnnotationStatus(
                    has_annotations=has_annotations,
                    verified=has_annotations,
                    questioned=False,
                    labels=frozenset(labels),
                )

            document = cls.load(
                annotation_path,
                image_path=image_path,
                image_data=image_data,
            )
            return document.status
        except (AnnotationDocumentError, OSError, ValueError, KeyError):
            return AnnotationStatus(False, False, False, frozenset())

    @property
    def status(self):
        return AnnotationStatus(
            has_annotations=bool(self.boxes),
            verified=self.verified,
            questioned=self.questioned,
            labels=frozenset(
                box.label for box in self.boxes if box.label
            ),
        )

    def save(self, annotation_path, annotation_format):
        target_path = _with_extension(
            annotation_path,
            annotation_format.extension,
        )
        image = _as_qimage(self.image_path, self.image_data)
        image_shape = [
            image.height(),
            image.width(),
            1 if image.isGrayscale() else 3,
        ]
        folder_name = os.path.basename(os.path.dirname(self.image_path))
        file_name = os.path.basename(self.image_path)
        writer_shapes = [box.to_writer_shape() for box in self.boxes]

        try:
            if annotation_format is AnnotationFormat.PASCAL_VOC:
                writer = PascalVocWriter(
                    folder_name,
                    file_name,
                    image_shape,
                    local_img_path=self.image_path,
                )
                _add_boxes(writer, self.boxes)
                writer.verified = self.verified
                writer.questioned = self.questioned
                writer.save(target_file=target_path)
            elif annotation_format is AnnotationFormat.YOLO:
                writer = YOLOWriter(
                    folder_name,
                    file_name,
                    image_shape,
                    local_img_path=self.image_path,
                )
                _add_boxes(writer, self.boxes)
                writer.verified = self.verified
                writer.questioned = self.questioned
                writer.save(
                    target_file=target_path,
                    class_list=list(
                        _labels_in_order(
                            list(self.class_names)
                            + [box.label for box in self.boxes]
                        )
                    ),
                )
            elif annotation_format is AnnotationFormat.CREATE_ML:
                writer = CreateMLWriter(
                    folder_name,
                    file_name,
                    image_shape,
                    writer_shapes,
                    target_path,
                    local_img_path=self.image_path,
                )
                writer.verified = self.verified
                writer.questioned = self.questioned
                writer.write()
            else:
                raise AnnotationDocumentError(
                    "Unsupported annotation format: %r"
                    % (annotation_format,)
                )
        except Exception as error:
            if isinstance(error, AnnotationDocumentError):
                raise
            raise AnnotationDocumentError(str(error)) from error

        return target_path

    def create_shapes(self, snap_point, color_for_label):
        shapes = []
        snapped_any = False
        for box in self.boxes:
            shape, snapped = box.to_shape(snap_point, color_for_label)
            shapes.append(shape)
            snapped_any = snapped_any or snapped
        return shapes, snapped_any

    def toggle_verified(self):
        self.verified = not self.verified
        if self.verified:
            self.questioned = False

    def toggle_questioned(self):
        self.questioned = not self.questioned
        if self.questioned:
            self.verified = False


def _as_qimage(image_path, image_data):
    if isinstance(image_data, QImage):
        return image_data
    image = QImage()
    if image_data:
        image = QImage.fromData(image_data)
    if image.isNull() and image_path:
        image.load(os.fspath(image_path))
    if image.isNull():
        raise AnnotationDocumentError(
            "Unable to read image data for annotation document"
        )
    return image


def _with_extension(path, extension):
    path = os.fspath(path)
    if path.lower().endswith(extension):
        return path
    return path + extension


def _points_to_bnd_box(points):
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    return (
        max(1, int(min(x_values))),
        max(1, int(min(y_values))),
        int(max(x_values)),
        int(max(y_values)),
    )


def _add_boxes(writer, boxes):
    for box in boxes:
        x_min, y_min, x_max, y_max = _points_to_bnd_box(box.points)
        writer.add_bnd_box(
            x_min,
            y_min,
            x_max,
            y_max,
            box.label,
            int(box.difficult),
        )


def _labels_in_order(labels):
    seen = set()
    ordered = []
    for label in labels:
        if label and label not in seen:
            seen.add(label)
            ordered.append(label)
    return ordered


def _inspect_yolo(annotation_path):
    directory = os.path.dirname(os.path.abspath(annotation_path))
    class_path = os.path.join(directory, "classes.txt")
    with open(class_path, "r", encoding="utf8") as class_file:
        classes = [line.strip() for line in class_file if line.strip()]
    used_indexes = set()
    has_annotations = False
    with open(annotation_path, "r", encoding="utf8") as annotation_file:
        for line_number, line in enumerate(annotation_file, start=1):
            fields = line.split()
            if not fields:
                continue
            if len(fields) != 5:
                raise ValueError(
                    "Invalid YOLO annotation at line %d" % line_number
                )
            try:
                class_index = int(fields[0])
                x_center, y_center, width, height = (
                    float(value) for value in fields[1:]
                )
            except ValueError as error:
                raise ValueError(
                    "Invalid YOLO annotation at line %d" % line_number
                ) from error
            coordinates = (x_center, y_center, width, height)
            if (
                class_index < 0
                or class_index >= len(classes)
                or not all(math.isfinite(value) for value in coordinates)
                or not 0 <= x_center <= 1
                or not 0 <= y_center <= 1
                or not 0 < width <= 1
                or not 0 < height <= 1
            ):
                raise ValueError(
                    "Invalid YOLO annotation at line %d" % line_number
                )
            used_indexes.add(class_index)
            has_annotations = True
    return (
        [
            label
            for index, label in enumerate(classes)
            if index in used_indexes
        ],
        has_annotations,
    )


def _inspect_create_ml(annotation_path):
    with open(annotation_path, "r", encoding="utf8") as annotation_file:
        payload = json.load(annotation_file)
    labels = []
    has_annotations = False
    for image in payload:
        annotations = image.get("annotations", ())
        has_annotations = has_annotations or bool(annotations)
        labels.extend(
            annotation.get("label")
            for annotation in annotations
            if annotation.get("label")
        )
    return _labels_in_order(labels), has_annotations
