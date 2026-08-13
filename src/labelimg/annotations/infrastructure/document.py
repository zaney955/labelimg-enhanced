"""Physical annotation document readers and writers."""

from dataclasses import dataclass
import math
import os
from xml.etree import ElementTree

try:
    from PyQt5.QtGui import QImage
except ImportError:
    from PyQt4.QtGui import QImage

from labelimg.annotations.infrastructure.formats.create_ml import CreateMLReader, CreateMLWriter, JSON_EXT
from labelimg.annotations.infrastructure.formats.create_ml_collection import CreateMLAnnotationCollection
from labelimg.annotations.infrastructure.formats.pascal_voc import PascalVocReader, PascalVocWriter, XML_EXT
from labelimg.annotations.domain.model import (
    AnnotationBox,
    AnnotationDocument as DomainAnnotationDocument,
    AnnotationDocumentError,
    AnnotationFormat,
    AnnotationStatus,
)
from labelimg.annotations.infrastructure.formats.yolo import TXT_EXT, YOLOWriter, YoloReader










@dataclass(frozen=True)
class _LoadedAnnotation:
    boxes: tuple
    verified: bool
    questioned: bool
    record_name: str | None = None


class AnnotationDocument(DomainAnnotationDocument):

    @classmethod
    def load(cls, annotation_path, image_path, image_data):
        annotation_format = AnnotationFormat.from_path(annotation_path)
        try:
            loaded = _adapter_for(annotation_format).load(
                os.fspath(annotation_path),
                image_path,
                image_data,
            )
        except Exception as error:
            if isinstance(error, AnnotationDocumentError):
                raise
            raise AnnotationDocumentError(str(error)) from error

        return cls(
            image_path=os.fspath(image_path),
            image_data=image_data,
            boxes=loaded.boxes,
            class_names=tuple(
                _labels_in_order(
                    box.label for box in loaded.boxes
                )
            ),
            verified=loaded.verified,
            questioned=loaded.questioned,
            create_ml_record_name=loaded.record_name,
        )

    @classmethod
    def image_path_hint(cls, annotation_path):
        """Return an image path named by an annotation document, if any."""
        annotation_path = os.path.abspath(os.fspath(annotation_path))
        annotation_format = AnnotationFormat.from_path(annotation_path)
        try:
            return _adapter_for(annotation_format).image_path_hint(
                annotation_path
            )
        except (OSError, ValueError, ElementTree.ParseError):
            return None

    @classmethod
    def inspect(cls, annotation_path, image_path=None, image_data=None):
        annotation_format = AnnotationFormat.from_path(annotation_path)
        try:
            return _adapter_for(annotation_format).inspect(
                os.fspath(annotation_path),
                image_path,
                image_data,
            )
        except (AnnotationDocumentError, OSError, ValueError, KeyError):
            return AnnotationStatus(False, False, False, frozenset())

    @classmethod
    def inspect_content(
        cls,
        annotation_path,
        content,
        *,
        related_content=None,
    ):
        """Inspect already-read bytes without reopening physical resources."""
        annotation_format = AnnotationFormat.from_path(annotation_path)
        try:
            if annotation_format is AnnotationFormat.PASCAL_VOC:
                root = ElementTree.fromstring(content)
                review = root.attrib.get("verified")
                labels = frozenset(
                    value.strip()
                    for value in (
                        item.findtext("name", "")
                        for item in root.findall("object")
                    )
                    if value.strip()
                )
                return AnnotationStatus(
                    bool(root.findall("object")),
                    review == "yes",
                    review == "no",
                    labels,
                )
            if annotation_format is AnnotationFormat.YOLO:
                classes = (related_content or {}).get("classes.txt", b"")
                return _inspect_yolo_content(content, classes)
            collection = CreateMLAnnotationCollection.read(
                annotation_path,
                content=content,
            )
            return AnnotationStatus(
                collection.has_annotations,
                collection.verified,
                collection.questioned,
                frozenset(collection.labels),
            )
        except (
            AnnotationDocumentError,
            OSError,
            UnicodeError,
            ValueError,
            KeyError,
            ElementTree.ParseError,
        ):
            return AnnotationStatus(False, False, False, frozenset())


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

        try:
            _adapter_for(annotation_format).save(
                self,
                target_path,
                folder_name,
                file_name,
                image_shape,
            )
        except Exception as error:
            if isinstance(error, AnnotationDocumentError):
                raise
            raise AnnotationDocumentError(str(error)) from error

        return target_path


def load_document(annotation_path, image_path, image_data):
    return AnnotationDocument.load(annotation_path, image_path, image_data)


def inspect_document(annotation_path, image_path=None, image_data=None):
    return AnnotationDocument.inspect(annotation_path, image_path, image_data)


def image_path_hint(annotation_path):
    return AnnotationDocument.image_path_hint(annotation_path)


def save_document(document, annotation_path, annotation_format):
    return AnnotationDocument.save(document, annotation_path, annotation_format)





class _AnnotationFormatAdapter:
    def image_path_hint(self, annotation_path):
        return None

    def inspect(self, annotation_path, image_path, image_data):
        loaded = self.load(annotation_path, image_path, image_data)
        return _status_for_loaded(loaded)


class _PascalVocAdapter(_AnnotationFormatAdapter):
    def load(self, annotation_path, image_path, image_data):
        reader = PascalVocReader(annotation_path)
        return _loaded_from_reader(reader)

    def image_path_hint(self, annotation_path):
        root = ElementTree.parse(annotation_path).getroot()
        return _first_existing_image_path(
            annotation_path,
            (
                root.findtext("path"),
                root.findtext("filename"),
            ),
        )

    def save(
        self,
        document,
        target_path,
        folder_name,
        file_name,
        image_shape,
    ):
        writer = PascalVocWriter(
            folder_name,
            file_name,
            image_shape,
            local_img_path=document.image_path,
        )
        _add_boxes(writer, document.boxes)
        _set_writer_status(writer, document)
        writer.save(target_file=target_path)


class _YoloAdapter(_AnnotationFormatAdapter):
    def load(self, annotation_path, image_path, image_data):
        reader = YoloReader(
            annotation_path,
            _as_qimage(image_path, image_data),
        )
        return _loaded_from_reader(reader)

    def inspect(self, annotation_path, image_path, image_data):
        if image_data is not None:
            return super().inspect(
                annotation_path,
                image_path,
                image_data,
            )
        labels, has_annotations, verified, questioned = _inspect_yolo(
            annotation_path
        )
        return AnnotationStatus(
            has_annotations=has_annotations,
            verified=verified,
            questioned=questioned,
            labels=frozenset(labels),
        )

    def save(
        self,
        document,
        target_path,
        folder_name,
        file_name,
        image_shape,
    ):
        writer = YOLOWriter(
            folder_name,
            file_name,
            image_shape,
            local_img_path=document.image_path,
        )
        _add_boxes(writer, document.boxes)
        _set_writer_status(writer, document)
        writer.save(
            target_file=target_path,
            class_list=list(
                _labels_in_order(
                    list(document.class_names)
                    + [box.label for box in document.boxes]
                )
            ),
        )


class _CreateMLAdapter(_AnnotationFormatAdapter):
    def load(self, annotation_path, image_path, image_data):
        reader = CreateMLReader(
            annotation_path,
            os.fspath(image_path),
        )
        return _loaded_from_reader(reader)

    def image_path_hint(self, annotation_path):
        collection = CreateMLAnnotationCollection.read(annotation_path)
        return _first_existing_image_path(
            annotation_path,
            collection.references,
        )

    def inspect(self, annotation_path, image_path, image_data):
        if image_path is not None:
            return super().inspect(
                annotation_path,
                image_path,
                image_data,
            )
        (
            labels,
            has_annotations,
            verified,
            questioned,
        ) = _inspect_create_ml(annotation_path)
        return AnnotationStatus(
            has_annotations=has_annotations,
            verified=verified,
            questioned=questioned,
            labels=frozenset(labels),
        )

    def save(
        self,
        document,
        target_path,
        folder_name,
        file_name,
        image_shape,
    ):
        writer = CreateMLWriter(
            folder_name,
            document.create_ml_record_name or file_name,
            image_shape,
            [box.to_writer_shape() for box in document.boxes],
            target_path,
            local_img_path=document.image_path,
        )
        _set_writer_status(writer, document)
        writer.write()


_FORMAT_ADAPTERS = {
    AnnotationFormat.PASCAL_VOC: _PascalVocAdapter(),
    AnnotationFormat.YOLO: _YoloAdapter(),
    AnnotationFormat.CREATE_ML: _CreateMLAdapter(),
}


def _adapter_for(annotation_format):
    try:
        return _FORMAT_ADAPTERS[annotation_format]
    except (KeyError, TypeError) as error:
        raise AnnotationDocumentError(
            "Unsupported annotation format: %r"
            % (annotation_format,)
        ) from error


def _loaded_from_reader(reader):
    boxes = tuple(
        AnnotationBox.from_reader_shape(shape)
        for shape in reader.get_shapes()
    )
    return _LoadedAnnotation(
        boxes=boxes,
        verified=bool(reader.verified),
        questioned=bool(reader.questioned),
        record_name=getattr(reader, "record_name", None),
    )


def _status_for_loaded(loaded):
    return AnnotationStatus(
        has_annotations=bool(loaded.boxes),
        verified=loaded.verified,
        questioned=loaded.questioned,
        labels=frozenset(
            box.label for box in loaded.boxes if box.label
        ),
    )


def _set_writer_status(writer, document):
    writer.verified = document.verified
    writer.questioned = document.questioned


def _first_existing_image_path(annotation_path, candidates):
    directory = os.path.dirname(os.path.abspath(annotation_path))
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
    verified = False
    questioned = False
    with open(annotation_path, "r", encoding="utf8") as annotation_file:
        for line_number, line in enumerate(annotation_file, start=1):
            fields = line.split()
            if not fields:
                continue
            if line.lstrip().startswith("#"):
                text = line.strip().casefold()
                if text.startswith("# labelimg-review:"):
                    state = text.partition(":")[2].strip()
                    verified = state == "verified"
                    questioned = state == "questioned"
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
        verified,
        questioned,
    )


def _inspect_yolo_content(annotation_content, classes_content):
    classes = [
        line.strip()
        for line in classes_content.decode("utf8").splitlines()
        if line.strip()
    ]
    used_indexes = set()
    has_annotations = False
    verified = False
    questioned = False
    for line_number, line in enumerate(
        annotation_content.decode("utf8").splitlines(), start=1
    ):
        fields = line.split()
        if not fields:
            continue
        if line.lstrip().startswith("#"):
            text = line.strip().casefold()
            if text.startswith("# labelimg-review:"):
                state = text.partition(":")[2].strip()
                verified = state == "verified"
                questioned = state == "questioned"
            continue
        if len(fields) != 5:
            raise ValueError("Invalid YOLO annotation at line %d" % line_number)
        class_index = int(fields[0])
        coordinates = tuple(float(value) for value in fields[1:])
        x_center, y_center, width, height = coordinates
        if (
            class_index < 0
            or class_index >= len(classes)
            or not all(math.isfinite(value) for value in coordinates)
            or not 0 <= x_center <= 1
            or not 0 <= y_center <= 1
            or not 0 < width <= 1
            or not 0 < height <= 1
        ):
            raise ValueError("Invalid YOLO annotation at line %d" % line_number)
        used_indexes.add(class_index)
        has_annotations = True
    return AnnotationStatus(
        has_annotations,
        verified,
        questioned,
        frozenset(
            label
            for index, label in enumerate(classes)
            if index in used_indexes
        ),
    )


def _inspect_create_ml(annotation_path):
    collection = CreateMLAnnotationCollection.read(annotation_path)
    return (
        _labels_in_order(collection.labels),
        collection.has_annotations,
        collection.verified,
        collection.questioned,
    )
