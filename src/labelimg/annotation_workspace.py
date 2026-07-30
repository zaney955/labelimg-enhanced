"""Directory-level annotation paths, status, and candidate labels."""

from dataclasses import dataclass
import os

from labelimg.annotation_document import (
    AnnotationDocument,
    AnnotationDocumentError,
    AnnotationFormat,
    AnnotationStatus,
)


@dataclass(frozen=True)
class WorkspaceEntry:
    image_path: str
    paths: tuple
    status: AnnotationStatus

    def path_for(self, annotation_format):
        return self.paths[list(AnnotationFormat).index(annotation_format)]


@dataclass(frozen=True)
class WorkspaceDocument:
    annotation_path: str
    annotation_format: AnnotationFormat
    document: AnnotationDocument


@dataclass(frozen=True)
class WorkspaceSave:
    annotation_path: str
    document: AnnotationDocument | None
    removed: bool = False


class AnnotationWorkspace:
    """Keep annotation workspace policies and derived state consistent."""

    def __init__(self, save_dir=None):
        self._save_dir = (
            os.path.abspath(os.fspath(save_dir))
            if save_dir
            else None
        )
        self._labels_by_path = {}

    @property
    def save_dir(self):
        return self._save_dir

    @property
    def candidate_labels(self):
        discovered = set()
        for labels in self._labels_by_path.values():
            discovered.update(labels)
        return tuple(sorted(discovered, key=lambda label: label.casefold()))

    def set_save_dir(self, save_dir):
        self._save_dir = (
            os.path.abspath(os.fspath(save_dir))
            if save_dir
            else None
        )

    def entry(self, image_path):
        image_path = os.path.abspath(os.fspath(image_path))
        paths = self._paths_for_image(image_path)
        statuses = []
        for annotation_path in paths:
            if not os.path.isfile(annotation_path):
                continue
            statuses.append(
                AnnotationDocument.inspect(
                    annotation_path,
                    image_path=image_path,
                )
            )
        status = _merge_statuses(statuses)
        return WorkspaceEntry(image_path, paths, status)

    def load(self, annotation_path, image_path, image_data):
        annotation_path = os.path.abspath(os.fspath(annotation_path))
        annotation_format = AnnotationFormat.from_path(annotation_path)
        document = AnnotationDocument.load(
            annotation_path,
            image_path,
            image_data,
        )
        return WorkspaceDocument(
            annotation_path,
            annotation_format,
            document,
        )

    def load_for_image(self, image_path, image_data):
        for annotation_path in self.entry(image_path).paths:
            if os.path.isfile(annotation_path):
                try:
                    return self.load(
                        annotation_path,
                        image_path,
                        image_data,
                    )
                except AnnotationDocumentError as error:
                    raise AnnotationDocumentError(
                        "%s: %s" % (annotation_path, error)
                    ) from error
        return None

    def save(
        self,
        document,
        annotation_format,
        annotation_path=None,
    ):
        if annotation_path is None:
            annotation_path = self.entry(
                document.image_path
            ).path_for(annotation_format)
        annotation_path = os.path.abspath(os.fspath(annotation_path))
        if not annotation_path.lower().endswith(
            annotation_format.extension
        ):
            annotation_path += annotation_format.extension

        if (
            annotation_format is AnnotationFormat.PASCAL_VOC
            and not document.boxes
        ):
            removed = os.path.isfile(annotation_path)
            if removed:
                os.remove(annotation_path)
            self.record(annotation_path, ())
            return WorkspaceSave(
                annotation_path,
                None,
                removed=removed,
            )

        saved_path = document.save(annotation_path, annotation_format)
        self.record(
            saved_path,
            (box.label for box in document.boxes if box.label),
        )
        return WorkspaceSave(saved_path, document)

    def scan(self, directory):
        self._labels_by_path.clear()
        for root, _directories, files in os.walk(directory):
            for filename in files:
                if filename.casefold() == "classes.txt":
                    continue
                annotation_path = os.path.join(root, filename)
                try:
                    AnnotationFormat.from_path(annotation_path)
                except AnnotationDocumentError:
                    continue
                status = AnnotationDocument.inspect(annotation_path)
                self._labels_by_path[_cache_key(annotation_path)] = set(
                    status.labels
                )
        return self.candidate_labels

    def record(self, annotation_path, labels):
        self._labels_by_path[_cache_key(annotation_path)] = {
            label.strip()
            for label in labels
            if label and label.strip()
        }
        return self.candidate_labels

    def delete(self, image_path):
        removed = []
        for annotation_path in self._paths_for_image(image_path):
            if os.path.isfile(annotation_path):
                os.remove(annotation_path)
                removed.append(annotation_path)
            self._labels_by_path.pop(
                _cache_key(annotation_path),
                None,
            )
        return tuple(removed)

    def _paths_for_image(self, image_path):
        image_path = os.path.abspath(os.fspath(image_path))
        stem = os.path.splitext(image_path)[0]
        if self._save_dir:
            stem = os.path.join(
                self._save_dir,
                os.path.basename(stem),
            )
        return tuple(
            stem + annotation_format.extension
            for annotation_format in AnnotationFormat
        )


def _cache_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _merge_statuses(statuses):
    labels = set()
    for status in statuses:
        labels.update(status.labels)
    questioned = any(status.questioned for status in statuses)
    return AnnotationStatus(
        has_annotations=any(
            status.has_annotations for status in statuses
        ),
        verified=(
            not questioned
            and any(status.verified for status in statuses)
        ),
        questioned=questioned,
        labels=frozenset(labels),
    )
