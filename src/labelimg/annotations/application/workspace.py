"""Directory-level annotation paths, status, and candidate labels."""

from dataclasses import dataclass, replace
import hashlib
import os
from xml.etree import ElementTree

from labelimg.annotations.domain.model import (
    AnnotationDocumentError,
    AnnotationFormat,
    AnnotationStatus,
)
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations.infrastructure.formats.create_ml_collection import (
    CreateMLAnnotationCollection,
    CreateMLCollectionError,
    CreateMLCollectionFormatError,
    CreateMLRecordIdentity,
    is_absolute_image_reference,
    normalize_image_reference,
)
from labelimg.annotations.infrastructure.storage import (
    AnnotationResource,
    AnnotationSaveRequest,
    AnnotationStorageCoordinator,
    AtomicAnnotationWriter,
    MISSING_FINGERPRINT,
    ResourceFingerprint,
    fingerprint_path,
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
class WorkspaceDocumentChoice:
    annotation_path: str
    annotation_format: AnnotationFormat
    modified_ns: int


class AmbiguousAnnotationDocuments(AnnotationDocumentError):
    def __init__(self, image_path, choices):
        self.image_path = image_path
        self.choices = tuple(choices)
        super().__init__(
            "Multiple annotation formats exist for %s" % image_path
        )


@dataclass(frozen=True)
class WorkspaceSave:
    annotation_path: str
    document: AnnotationDocument | None
    removed: bool = False
    revision_id: int = 0
    fingerprints: tuple = ()


class AnnotationWorkspace:
    """Keep annotation workspace policies and derived state consistent."""

    def __init__(
        self,
        save_dir=None,
        writer=None,
        storage_coordinator=None,
    ):
        self._save_dir = (
            os.path.abspath(os.fspath(save_dir))
            if save_dir
            else None
        )
        self._labels_by_path = {}
        self._status_by_path = {}
        self._modified_ns_by_path = {}
        self._writer = writer or AtomicAnnotationWriter()
        self._storage = (
            storage_coordinator or AnnotationStorageCoordinator()
        )
        self._resource_fingerprints = {}
        self._resource_bytes = {}
        self._active_paths = {}
        self._ambiguous_annotation_paths = set()
        self._held_resources = {}
        self._create_ml_paths_by_image_name = {}
        self._create_ml_paths_by_match_key = {}
        self._create_ml_resource_keys = set()
        self._create_ml_labels_by_record = {}
        self._create_ml_status_by_record = {}
        self._ambiguous_create_ml_records = set()
        self._in_memory_labels_by_image = {}
        self._yolo_vocabulary = []
        self._scanned_directory = None

    @property
    def save_dir(self):
        return self._save_dir

    @property
    def storage_coordinator(self):
        return self._storage

    @property
    def yolo_vocabulary(self):
        return tuple(self._yolo_vocabulary)

    def reserve_yolo_labels(self, labels):
        for label in labels:
            label = str(label).strip()
            if label and label not in self._yolo_vocabulary:
                self._yolo_vocabulary.append(label)
        return self.yolo_vocabulary

    @property
    def candidate_labels(self):
        discovered = set()
        memory_path_keys = {
            path_key
            for path_key, _image_name, _labels
            in self._in_memory_labels_by_image.values()
        }
        selected = {
            _cache_key(path)
            for path in self._active_paths.values()
        }
        selected_stems = {
            _cache_key(os.path.splitext(path)[0])
            for path in self._active_paths.values()
        }
        for path_key, labels in self._labels_by_path.items():
            if (
                path_key in memory_path_keys
                and path_key not in self._create_ml_resource_keys
            ):
                continue
            if path_key in self._create_ml_resource_keys:
                continue
            if (
                _cache_key(os.path.splitext(path_key)[0])
                in selected_stems
                and path_key not in selected
            ):
                continue
            if (
                path_key in self._ambiguous_annotation_paths
                and path_key not in selected
            ):
                continue
            discovered.update(labels)
        memory_sources = {
            (path_key, image_name)
            for path_key, image_name, _labels
            in self._in_memory_labels_by_image.values()
        }
        selected_create_ml_sources = set()
        for image_key, path in self._active_paths.items():
            if not str(path).lower().endswith(
                AnnotationFormat.CREATE_ML.extension
            ):
                continue
            path_key = _cache_key(path)
            selected_create_ml_sources.update(
                source
                for source in self._create_ml_labels_by_record
                if source[0] == path_key
                and CreateMLRecordIdentity(
                    path, source[1]
                ).matches(image_key)
            )
        for source, labels in self._create_ml_labels_by_record.items():
            if (
                source not in memory_sources
                and not (
                    source in self._ambiguous_create_ml_records
                    and source not in selected_create_ml_sources
                )
                and not (
                    source[0] in self._ambiguous_annotation_paths
                    and source[0] not in selected
                )
            ):
                discovered.update(labels)
        for _path_key, _image_name, labels in (
            self._in_memory_labels_by_image.values()
        ):
            discovered.update(labels)
        return tuple(
            sorted(
                discovered,
                key=lambda label: (label.casefold(), label),
            )
        )

    def set_save_dir(self, save_dir):
        new_value = (
            os.path.abspath(os.fspath(save_dir))
            if save_dir
            else None
        )
        if new_value != self._save_dir:
            self._active_paths.clear()
            self._ambiguous_annotation_paths.clear()
            self._ambiguous_create_ml_records.clear()
            self._in_memory_labels_by_image.clear()
            self._yolo_vocabulary.clear()
        self._save_dir = new_value

    def entry(self, image_path):
        image_path = os.path.abspath(os.fspath(image_path))
        paths = self._paths_for_image(image_path)
        statuses = []
        for annotation_path in self._document_paths_for_image(image_path):
            path_key = _cache_key(annotation_path)
            if (
                annotation_path.lower().endswith(
                    AnnotationFormat.CREATE_ML.extension
                )
                and path_key in self._create_ml_resource_keys
            ):
                status = self._create_ml_status_for_image(
                    annotation_path, image_path
                )
                if status is not None:
                    statuses.append(status)
                continue
            cached = self._status_by_path.get(path_key)
            if cached is not None:
                statuses.append(cached)
                continue
            if self._path_covered_by_scan(annotation_path):
                continue
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
        self.validate_annotation_resource(annotation_path)
        document = AnnotationDocument.load(
            annotation_path,
            image_path,
            image_data,
        )
        for resource in annotation_resources(
            annotation_format,
            annotation_path,
        ):
            resource_key = _cache_key(resource)
            if resource_key not in self._held_resources:
                self._resource_fingerprints[resource_key] = (
                    fingerprint_path(resource)
                )
                self._remember_resource_bytes(resource)
        return WorkspaceDocument(
            annotation_path,
            annotation_format,
            document,
        )

    @staticmethod
    def validate_annotation_resource(annotation_path):
        """Reject incomplete external files before they can look empty."""
        path = os.path.abspath(os.fspath(annotation_path))
        annotation_format = AnnotationFormat.from_path(path)
        try:
            if annotation_format is AnnotationFormat.PASCAL_VOC:
                root = ElementTree.parse(path).getroot()
                if root.tag != "annotation":
                    raise AnnotationDocumentError(
                        "Pascal VOC root element must be annotation"
                    )
                return
            if annotation_format is AnnotationFormat.CREATE_ML:
                AnnotationWorkspace.validate_create_ml_resource(path)
                return
            with open(path, "r", encoding="utf8") as source:
                for line_number, line in enumerate(source, 1):
                    fields = line.split()
                    if not fields:
                        continue
                    if len(fields) != 5:
                        raise AnnotationDocumentError(
                            "Invalid YOLO record on line %d" % line_number
                        )
                    int(fields[0])
                    tuple(float(value) for value in fields[1:])
        except AnnotationDocumentError:
            raise
        except Exception as error:
            raise AnnotationDocumentError(str(error)) from error

    def load_for_image(self, image_path, image_data):
        image_key = _cache_key(image_path)
        choices = self.document_choices(image_path)
        if not choices:
            return None
        active = self._active_paths.get(image_key)
        if active is None:
            if len(choices) > 1:
                raise AmbiguousAnnotationDocuments(
                    image_path,
                    choices,
                )
            active = choices[0].annotation_path
            self._active_paths[image_key] = active
        if not any(
            _cache_key(choice.annotation_path) == _cache_key(active)
            for choice in choices
        ):
            self._active_paths.pop(image_key, None)
            return self.load_for_image(image_path, image_data)
        try:
            return self.load(active, image_path, image_data)
        except AnnotationDocumentError as error:
            raise AnnotationDocumentError(
                "%s: %s" % (active, error)
            ) from error
        return None

    def document_choices(self, image_path):
        choices = []
        for annotation_path in self._document_paths_for_image(image_path):
            path_key = _cache_key(annotation_path)
            modified_ns = self._modified_ns_by_path.get(path_key)
            if modified_ns is None:
                if self._path_covered_by_scan(annotation_path):
                    continue
                try:
                    modified_ns = os.stat(annotation_path).st_mtime_ns
                except FileNotFoundError:
                    continue
            choices.append(WorkspaceDocumentChoice(
                annotation_path=annotation_path,
                annotation_format=AnnotationFormat.from_path(annotation_path),
                modified_ns=modified_ns,
            ))
        return tuple(choices)

    def refresh_document_choices(self, image_path):
        """Refresh only the document paths relevant to one image."""
        image_path = os.path.abspath(os.fspath(image_path))
        paths = set(self._paths_for_image(image_path))
        active = self._active_paths.get(_cache_key(image_path))
        if active:
            paths.add(active)
        for match_key in _image_match_keys(image_path):
            paths.update(self._create_ml_paths_by_match_key.get(match_key, ()))
        for annotation_path in paths:
            path_key = _cache_key(annotation_path)
            try:
                stat = os.stat(annotation_path)
            except FileNotFoundError:
                self._modified_ns_by_path.pop(path_key, None)
                self._labels_by_path.pop(path_key, None)
                self._status_by_path.pop(path_key, None)
                continue
            self.validate_annotation_resource(annotation_path)
            status = AnnotationDocument.inspect(
                annotation_path,
                image_path=image_path,
            )
            self._modified_ns_by_path[path_key] = stat.st_mtime_ns
            self._status_by_path[path_key] = status
            self._labels_by_path[path_key] = set(status.labels)
            if annotation_path.lower().endswith(
                AnnotationFormat.CREATE_ML.extension
            ):
                self._record_create_ml_resource(annotation_path)
        return self.document_choices(image_path)

    def _path_covered_by_scan(self, path):
        if not self._scanned_directory:
            return False
        try:
            return os.path.commonpath((
                self._scanned_directory,
                _cache_key(path),
            )) == self._scanned_directory
        except ValueError:
            return False

    def select_active_document(self, image_path, annotation_path):
        choices = self.document_choices(image_path)
        selected = next(
            (
                choice.annotation_path
                for choice in choices
                if _cache_key(choice.annotation_path)
                == _cache_key(annotation_path)
            ),
            None,
        )
        if selected is None:
            raise AnnotationDocumentError(
                "Annotation choice does not belong to this image"
            )
        self._active_paths[_cache_key(image_path)] = selected
        return selected

    def active_document_path(self, image_path):
        return self._active_paths.get(_cache_key(image_path))

    def migrate_images(self, path_mapping, target_mapping=None):
        target_mapping = target_mapping or {}
        for source, destination in path_mapping.items():
            source_key = _cache_key(source)
            active = self._active_paths.pop(source_key, None)
            if active is not None:
                active = target_mapping.get(source, active)
                self._active_paths[_cache_key(destination)] = active
            memory = self._in_memory_labels_by_image.pop(
                source_key, None
            )
            if memory is not None:
                path_key, _image_name, labels = memory
                new_target = target_mapping.get(source)
                if new_target is not None:
                    path_key = _cache_key(new_target)
                self._in_memory_labels_by_image[
                    _cache_key(destination)
                ] = (
                    path_key,
                    normalize_image_reference(
                        os.path.basename(destination)
                    ),
                    labels,
                )

    def save(
        self,
        document,
        annotation_format,
        annotation_path=None,
        revision_id=0,
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
        if annotation_format is AnnotationFormat.CREATE_ML:
            document = self._bind_create_ml_record(
                document, annotation_path
            )

        empty_pascal = (
            annotation_format is AnnotationFormat.PASCAL_VOC
            and not document.boxes
            and not document.verified
            and not document.questioned
        )
        resources = annotation_resources(
            annotation_format,
            annotation_path,
        )
        resource_bindings = tuple(
            AnnotationResource(
                resource,
                self._resource_fingerprints.get(
                    _cache_key(resource)
                ),
            )
            for resource in resources
        )
        request = AnnotationSaveRequest(
            image_key=document.image_path,
            revision_id=revision_id,
            target=annotation_path,
            resources=resource_bindings,
            payload=document,
        )
        storage_result = self._storage.save(
            request,
            lambda _request: self._writer.write(
                document,
                annotation_format,
                annotation_path,
                base_resources={
                    resource: self._resource_bytes[
                        _cache_key(resource)
                    ]
                    for resource in resources
                    if self._resource_bytes.get(
                        _cache_key(resource)
                    ) is not None
                },
                precommit=_request.precommit,
            ),
        )
        saved_path, removed = storage_result.writer_result
        self._active_paths[_cache_key(document.image_path)] = saved_path
        for resource, fingerprint in storage_result.fingerprints:
            self._resource_fingerprints[_cache_key(resource)] = fingerprint
            self._remember_resource_bytes(resource)
        if empty_pascal:
            self.record(annotation_path, ())
            self._status_by_path[_cache_key(annotation_path)] = (
                AnnotationStatus(False, False, False, frozenset())
            )
            self._in_memory_labels_by_image.pop(
                _cache_key(document.image_path), None
            )
            return WorkspaceSave(
                annotation_path,
                None,
                removed=removed,
                revision_id=storage_result.revision_id,
                fingerprints=storage_result.fingerprints,
            )

        labels = (box.label for box in document.boxes if box.label)
        self.record(saved_path, labels)
        self._status_by_path[_cache_key(saved_path)] = AnnotationStatus(
            bool(document.boxes),
            document.verified,
            document.questioned,
            frozenset(box.label for box in document.boxes if box.label),
        )
        self._in_memory_labels_by_image.pop(
            _cache_key(document.image_path), None
        )
        return WorkspaceSave(
            saved_path,
            document,
            revision_id=storage_result.revision_id,
            fingerprints=storage_result.fingerprints,
        )

    def save_createml_batch(self, revision_documents, annotation_path):
        """Atomically save the latest immutable revision for many images."""
        annotation_path = os.path.abspath(os.fspath(annotation_path))
        if not annotation_path.lower().endswith(
            AnnotationFormat.CREATE_ML.extension
        ):
            annotation_path += AnnotationFormat.CREATE_ML.extension
        resources = annotation_resources(
            AnnotationFormat.CREATE_ML, annotation_path
        )
        bindings = tuple(
            AnnotationResource(
                resource,
                self._resource_fingerprints.get(
                    _cache_key(resource)
                ),
            )
            for resource in resources
        )
        revision_documents = tuple(
            (
                revision_id,
                self._bind_create_ml_record(document, annotation_path),
            )
            for revision_id, document in revision_documents
        )
        requests = tuple(
            AnnotationSaveRequest(
                image_key=document.image_path,
                revision_id=revision_id,
                target=annotation_path,
                resources=bindings,
                payload=document,
            )
            for revision_id, document in revision_documents
        )
        storage_results = self._storage.save_batch(
            requests,
            lambda _requests: self._writer.write_createml_collection(
                tuple(document for _revision, document in revision_documents),
                annotation_path,
                base_resources={
                    resource: self._resource_bytes[
                        _cache_key(resource)
                    ]
                    for resource in resources
                    if self._resource_bytes.get(
                        _cache_key(resource)
                    ) is not None
                },
                precommit=_requests[0].precommit,
            ),
        )
        for resource, fingerprint in storage_results[0].fingerprints:
            self._resource_fingerprints[_cache_key(resource)] = fingerprint
            self._remember_resource_bytes(resource)
        saves = []
        for storage_result, (_revision, document) in zip(
            storage_results, revision_documents
        ):
            self._active_paths[_cache_key(document.image_path)] = (
                annotation_path
            )
            saves.append(
                WorkspaceSave(
                    annotation_path,
                    document,
                    revision_id=storage_result.revision_id,
                    fingerprints=storage_result.fingerprints,
                )
            )
        self.record(
            annotation_path,
            (
                box.label
                for _revision, document in revision_documents
                for box in document.boxes
                if box.label
            ),
        )
        for _revision, document in revision_documents:
            self._in_memory_labels_by_image.pop(
                _cache_key(document.image_path), None
            )
        return tuple(saves)

    def scan(self, directory, force=True):
        directory = os.path.abspath(os.fspath(directory))
        if (
            not force
            and self._scanned_directory == _cache_key(directory)
        ):
            return self.candidate_labels
        held_fingerprints = {
            key: value
            for key, value in self._resource_fingerprints.items()
            if key in self._held_resources
        }
        held_bytes = {
            key: value
            for key, value in self._resource_bytes.items()
            if key in self._held_resources
        }
        self._labels_by_path.clear()
        self._status_by_path.clear()
        self._modified_ns_by_path.clear()
        self._resource_fingerprints.clear()
        self._resource_bytes.clear()
        self._resource_fingerprints.update(held_fingerprints)
        self._resource_bytes.update(held_bytes)
        self._ambiguous_annotation_paths.clear()
        self._ambiguous_create_ml_records.clear()
        self._create_ml_paths_by_image_name.clear()
        self._create_ml_paths_by_match_key.clear()
        self._create_ml_resource_keys.clear()
        self._create_ml_labels_by_record.clear()
        self._create_ml_status_by_record.clear()
        format_paths_by_stem = {}
        annotation_paths_by_filename_stem = {}
        annotation_paths = []
        resource_paths = set()
        for root, _directories, filenames in os.walk(directory):
            for filename in filenames:
                path = os.path.abspath(os.path.join(root, filename))
                if filename.casefold() == "classes.txt":
                    resource_paths.add(path)
                    continue
                try:
                    annotation_format = AnnotationFormat.from_path(path)
                except AnnotationDocumentError:
                    continue
                annotation_paths.append((path, annotation_format))
                resource_paths.update(annotation_resources(annotation_format, path))

        contents = {}
        for resource in resource_paths:
            key = _cache_key(resource)
            try:
                stat = os.stat(resource)
                with open(resource, "rb") as source:
                    content = source.read()
            except FileNotFoundError:
                contents[key] = None
                if key not in self._held_resources:
                    self._resource_fingerprints[key] = MISSING_FINGERPRINT
                    self._resource_bytes[key] = None
                continue
            contents[key] = content
            self._modified_ns_by_path[key] = stat.st_mtime_ns
            if key not in self._held_resources:
                self._resource_fingerprints[key] = ResourceFingerprint(
                    exists=True,
                    size=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                    sha256=hashlib.sha256(content).hexdigest(),
                )
                self._resource_bytes[key] = content

        for resource in resource_paths:
            if os.path.basename(resource).casefold() != "classes.txt":
                continue
            content = contents.get(_cache_key(resource))
            if content is not None:
                try:
                    self.reserve_yolo_labels(
                        line.strip()
                        for line in content.decode("utf8").splitlines()
                    )
                except UnicodeError:
                    pass

        for annotation_path, annotation_format in annotation_paths:
                path_key = _cache_key(annotation_path)
                content = contents.get(path_key)
                if content is None:
                    continue
                related = {}
                if annotation_format is AnnotationFormat.YOLO:
                    class_path = os.path.join(
                        os.path.dirname(annotation_path), "classes.txt"
                    )
                    related["classes.txt"] = contents.get(
                        _cache_key(class_path)
                    ) or b""
                status = AnnotationDocument.inspect_content(
                    annotation_path,
                    content,
                    related_content=related,
                )
                path_key = _cache_key(annotation_path)
                self._status_by_path[path_key] = status
                self._labels_by_path[path_key] = set(
                    status.labels
                )
                if annotation_format is AnnotationFormat.CREATE_ML:
                    self._record_create_ml_resource(
                        annotation_path, content=content
                    )
                stem_key = _cache_key(
                    os.path.splitext(annotation_path)[0]
                )
                format_paths_by_stem.setdefault(
                    stem_key,
                    set(),
                ).add(path_key)
                annotation_paths_by_filename_stem.setdefault(
                    os.path.splitext(
                        os.path.basename(annotation_path)
                    )[0].casefold(),
                    set(),
                ).add(path_key)
        for paths in format_paths_by_stem.values():
            if len(paths) > 1:
                self._ambiguous_annotation_paths.update(paths)
        for source in self._create_ml_labels_by_record:
            source_path, image_name = source
            image_stem = os.path.splitext(
                os.path.basename(image_name)
            )[0].casefold()
            competing_paths = {
                path
                for path in annotation_paths_by_filename_stem.get(
                    image_stem, ()
                )
                if path != source_path
            }
            if competing_paths:
                self._ambiguous_create_ml_records.add(source)
                self._ambiguous_annotation_paths.update(competing_paths)
        self._scanned_directory = _cache_key(directory)
        return self.candidate_labels

    def adopt_index(self, indexed_workspace):
        """Adopt a completed session index without replacing live edit state."""
        held_fingerprints = {
            key: self._resource_fingerprints.get(key)
            for key in self._held_resources
        }
        held_bytes = {
            key: self._resource_bytes.get(key)
            for key in self._held_resources
        }
        for name in (
            "_labels_by_path",
            "_status_by_path",
            "_modified_ns_by_path",
            "_resource_fingerprints",
            "_resource_bytes",
            "_ambiguous_annotation_paths",
            "_create_ml_paths_by_image_name",
            "_create_ml_paths_by_match_key",
            "_create_ml_resource_keys",
            "_create_ml_labels_by_record",
            "_create_ml_status_by_record",
            "_ambiguous_create_ml_records",
            "_yolo_vocabulary",
            "_scanned_directory",
        ):
            value = getattr(indexed_workspace, name)
            if isinstance(value, dict):
                value = {
                    key: set(item) if isinstance(item, set) else item
                    for key, item in value.items()
                }
            elif isinstance(value, set):
                value = set(value)
            elif isinstance(value, list):
                value = list(value)
            setattr(self, name, value)
        self._resource_fingerprints.update(
            (key, value) for key, value in held_fingerprints.items()
            if value is not None
        )
        self._resource_bytes.update(held_bytes)
        return self.candidate_labels

    def record(self, annotation_path, labels):
        if str(annotation_path).lower().endswith(
            AnnotationFormat.CREATE_ML.extension
        ) and os.path.isfile(annotation_path):
            self._record_create_ml_resource(annotation_path)
            return self.candidate_labels
        self._labels_by_path[_cache_key(annotation_path)] = {
            label.strip()
            for label in labels
            if label and label.strip()
        }
        return self.candidate_labels

    def record_document(self, image_path, annotation_path, labels):
        image_key = _cache_key(image_path)
        annotation_path = os.path.abspath(
            os.fspath(annotation_path)
        )
        self._active_paths[image_key] = annotation_path
        labels = frozenset(
            label.strip()
            for label in labels
            if label and label.strip()
        )
        if not annotation_path.lower().endswith(
            AnnotationFormat.CREATE_ML.extension
        ):
            self._status_by_path[_cache_key(annotation_path)] = (
                AnnotationStatus(bool(labels), False, False, labels)
            )
        if annotation_path.lower().endswith(
            AnnotationFormat.CREATE_ML.extension
        ):
            path_key = _cache_key(annotation_path)
            matching_sources = [
                source
                for source in self._create_ml_labels_by_record
                if source[0] == path_key
                and CreateMLRecordIdentity(
                    annotation_path, source[1]
                ).matches(image_path)
            ]
            record_key = (
                matching_sources[0][1]
                if len(matching_sources) == 1
                else normalize_image_reference(
                    os.path.basename(image_path)
                )
            )
            self._in_memory_labels_by_image[image_key] = (
                path_key,
                record_key,
                labels,
            )
            return self.candidate_labels
        self._in_memory_labels_by_image[image_key] = (
            _cache_key(annotation_path),
            normalize_image_reference(os.path.basename(image_path)),
            labels,
        )
        return self.candidate_labels

    def _record_create_ml_resource(self, annotation_path, content=None):
        path = os.path.abspath(os.fspath(annotation_path))
        path_key = _cache_key(path)
        self._create_ml_resource_keys.add(path_key)
        for source in tuple(self._create_ml_labels_by_record):
            if source[0] == path_key:
                self._create_ml_labels_by_record.pop(source, None)
                self._create_ml_status_by_record.pop(source, None)
        for paths in self._create_ml_paths_by_image_name.values():
            paths.discard(path)
        try:
            collection = CreateMLAnnotationCollection.read(
                path, content=content
            ) if content is not None else CreateMLAnnotationCollection.read(path)
        except (OSError, CreateMLCollectionError):
            return
        for record in collection.records:
            image_name_key = record.identity.reference_key
            self._create_ml_paths_by_image_name.setdefault(
                image_name_key, set()
            ).add(path)
            for match_key in _create_ml_match_keys(path, record.reference):
                self._create_ml_paths_by_match_key.setdefault(
                    match_key, set()
                ).add(path)
            self._create_ml_labels_by_record[
                (path_key, image_name_key)
            ] = set(record.labels)
            self._create_ml_status_by_record[
                (path_key, image_name_key)
            ] = AnnotationStatus(
                record.has_annotations,
                record.verified,
                record.questioned,
                frozenset(record.labels),
            )
            for match_key in _create_ml_match_keys(path, record.reference):
                self._create_ml_status_by_record[
                    (path_key, match_key)
                ] = self._create_ml_status_by_record[
                    (path_key, image_name_key)
                ]

    def _bind_create_ml_record(self, document, annotation_path):
        if document.create_ml_record_name:
            return document
        path = os.path.abspath(os.fspath(annotation_path))
        content = self._resource_bytes.get(_cache_key(path))
        try:
            collection = (
                CreateMLAnnotationCollection.read(
                    path, content=content
                )
                if content is not None
                else CreateMLAnnotationCollection.read(
                    path, missing_ok=True
                )
            )
        except FileNotFoundError:
            return document
        except CreateMLCollectionFormatError:
            return document
        except (OSError, CreateMLCollectionError) as error:
            raise AnnotationDocumentError(
                "Could not resolve CreateML record identity: %s" % error
            ) from error
        if not len(collection):
            return document
        try:
            record = collection.resolve(document.image_path)
        except CreateMLCollectionError as error:
            raise AnnotationDocumentError(
                str(error)
            ) from error
        return replace(
            document, create_ml_record_name=record.reference
        )

    def _document_paths_for_image(self, image_path):
        paths = list(self._paths_for_image(image_path))
        matched = set()
        for key in _image_match_keys(image_path):
            matched.update(self._create_ml_paths_by_match_key.get(key, ()))
        for path in sorted(matched, key=lambda value: value.casefold()):
            if path not in paths:
                paths.append(path)
        return tuple(paths)

    def _create_ml_status_for_image(self, annotation_path, image_path):
        path_key = _cache_key(annotation_path)
        matches = []
        for key in _image_match_keys(image_path):
            status = self._create_ml_status_by_record.get((path_key, key))
            if status is not None and status not in matches:
                matches.append(status)
        return _merge_statuses(matches) if matches else None

    def accept_resource_fingerprints(self, resources):
        """Adopt verified external identities for an explicit overwrite."""
        for resource in resources:
            self._resource_fingerprints[_cache_key(resource)] = (
                fingerprint_path(resource)
            )

    def create_ml_image_count(self, annotation_path):
        """Count the complete retained/current collection, including unopened images."""
        return len(self.create_ml_image_names(annotation_path))

    def create_ml_image_names(
        self, annotation_path, include_external=True
    ):
        path = os.path.abspath(os.fspath(annotation_path))
        content = self._resource_bytes.get(_cache_key(path))
        names = []
        if content is not None:
            try:
                names.extend(
                    CreateMLAnnotationCollection.read(
                        path, content=content
                    ).normalized_references
                )
            except CreateMLCollectionError:
                pass
        if include_external or content is None:
            try:
                names.extend(
                    CreateMLAnnotationCollection.read(
                        path
                    ).normalized_references
                )
            except (OSError, CreateMLCollectionError):
                pass
        return tuple(dict.fromkeys(names))

    def create_ml_image_keys(self, annotation_path, image_keys):
        identities = tuple(
            CreateMLRecordIdentity(annotation_path, reference)
            for reference in self.create_ml_image_names(annotation_path)
        )
        return tuple(
            image_key
            for image_key in image_keys
            if any(identity.matches(image_key) for identity in identities)
        )

    @staticmethod
    def validate_create_ml_resource(annotation_path):
        try:
            collection = CreateMLAnnotationCollection.read(
                annotation_path,
                strict=True,
            )
        except (OSError, CreateMLCollectionError) as error:
            raise AnnotationDocumentError(
                str(error)
            ) from error
        return collection.records

    def hold_resource(self, path, owner=None):
        key = _cache_key(path)
        if owner is None:
            owner = ("anonymous", key)
        self._held_resources.setdefault(key, set()).add(owner)

    def release_resource(self, path, owner=None):
        key = _cache_key(path)
        owners = self._held_resources.get(key)
        if not owners:
            return
        if owner is None:
            owner = ("anonymous", key)
        owners.discard(owner)
        if not owners:
            self._held_resources.pop(key, None)

    def refresh_resource(self, path):
        key = _cache_key(path)
        self._resource_fingerprints[key] = fingerprint_path(path)
        self._remember_resource_bytes(path)

    def apply_transaction_resources(self, fingerprints, contents):
        for key, fingerprint in fingerprints.items():
            self._resource_fingerprints[key] = fingerprint
        for key, content in contents.items():
            self._resource_bytes[key] = content

    def _remember_resource_bytes(self, resource):
        key = _cache_key(resource)
        try:
            with open(resource, "rb") as source:
                self._resource_bytes[key] = source.read()
        except FileNotFoundError:
            self._resource_bytes[key] = None

    def delete(self, image_path, remover=None):
        """Remove active-location annotations and update label discovery.

        File-list operations use AnnotationFileService for the broader
        both-location and shared-CreateML policy. This method remains as the
        recoverable compatibility boundary for workspace callers.
        """
        if remover is None:
            raise ValueError(
                "annotation deletion requires a recoverable remover"
            )
        removed = []
        for annotation_path in self._paths_for_image(image_path):
            if os.path.isfile(annotation_path):
                remover(annotation_path)
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


def _create_ml_match_keys(collection_path, reference):
    reference_key = normalize_image_reference(reference)
    if is_absolute_image_reference(reference):
        return (("absolute", reference_key),)
    if "\\" not in reference_key:
        return (("basename", reference_key),)
    resolved = normalize_image_reference(os.path.abspath(os.path.join(
        os.path.dirname(collection_path),
        *reference_key.split("\\"),
    )))
    return (
        ("suffix", reference_key),
        ("absolute", resolved),
    )


def _image_match_keys(image_path):
    normalized = normalize_image_reference(os.path.abspath(os.fspath(image_path)))
    parts = normalized.split("\\")
    keys = [
        ("absolute", normalized),
        ("basename", parts[-1]),
    ]
    keys.extend(
        ("suffix", "\\".join(parts[index:]))
        for index in range(1, len(parts) - 1)
    )
    return tuple(keys)


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


def annotation_resources(annotation_format, annotation_path):
    annotation_path = os.path.abspath(os.fspath(annotation_path))
    if annotation_format is AnnotationFormat.YOLO:
        return (
            annotation_path,
            os.path.join(
                os.path.dirname(annotation_path),
                "classes.txt",
            ),
        )
    return (annotation_path,)
