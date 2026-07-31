"""Directory-level annotation paths, status, and candidate labels."""

from dataclasses import dataclass
import json
import os

from labelimg.annotation_document import (
    AnnotationDocument,
    AnnotationDocumentError,
    AnnotationFormat,
    AnnotationStatus,
)
from labelimg.file_operations import move_to_recycle_bin
from labelimg.annotation_storage import (
    AnnotationResource,
    AnnotationSaveRequest,
    AnnotationStorageCoordinator,
    AtomicAnnotationWriter,
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
        self._writer = writer or AtomicAnnotationWriter()
        self._storage = (
            storage_coordinator or AnnotationStorageCoordinator()
        )
        self._resource_fingerprints = {}
        self._resource_bytes = {}
        self._active_paths = {}
        self._ambiguous_annotation_paths = set()
        self._held_resources = {}

    @property
    def save_dir(self):
        return self._save_dir

    @property
    def storage_coordinator(self):
        return self._storage

    @property
    def candidate_labels(self):
        discovered = set()
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
        self._save_dir = new_value

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
        return tuple(
            WorkspaceDocumentChoice(
                annotation_path=annotation_path,
                annotation_format=AnnotationFormat.from_path(
                    annotation_path
                ),
                modified_ns=os.stat(annotation_path).st_mtime_ns,
            )
            for annotation_path in self.entry(image_path).paths
            if os.path.isfile(annotation_path)
        )

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
            return WorkspaceSave(
                annotation_path,
                None,
                removed=removed,
                revision_id=storage_result.revision_id,
                fingerprints=storage_result.fingerprints,
            )

        labels = (
            AnnotationDocument.inspect(saved_path).labels
            if annotation_format is AnnotationFormat.CREATE_ML
            else (box.label for box in document.boxes if box.label)
        )
        self.record(saved_path, labels)
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
        revision_documents = tuple(revision_documents)
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
            AnnotationDocument.inspect(annotation_path).labels,
        )
        return tuple(saves)

    def scan(self, directory):
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
        self._resource_fingerprints.clear()
        self._resource_bytes.clear()
        self._resource_fingerprints.update(held_fingerprints)
        self._resource_bytes.update(held_bytes)
        self._ambiguous_annotation_paths.clear()
        format_paths_by_stem = {}
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
                path_key = _cache_key(annotation_path)
                self._labels_by_path[path_key] = set(
                    status.labels
                )
                stem_key = _cache_key(
                    os.path.splitext(annotation_path)[0]
                )
                format_paths_by_stem.setdefault(
                    stem_key,
                    set(),
                ).add(path_key)
                annotation_format = AnnotationFormat.from_path(
                    annotation_path
                )
                for resource in annotation_resources(
                    annotation_format,
                    annotation_path,
                ):
                    resource_key = _cache_key(resource)
                    if resource_key not in self._held_resources:
                        self._resource_fingerprints[
                            resource_key
                        ] = fingerprint_path(resource)
                        self._remember_resource_bytes(resource)
        for paths in format_paths_by_stem.values():
            if len(paths) > 1:
                self._ambiguous_annotation_paths.update(paths)
        return self.candidate_labels

    def record(self, annotation_path, labels):
        self._labels_by_path[_cache_key(annotation_path)] = {
            label.strip()
            for label in labels
            if label and label.strip()
        }
        return self.candidate_labels

    def record_document(self, image_path, annotation_path, labels):
        self._active_paths[_cache_key(image_path)] = os.path.abspath(
            os.fspath(annotation_path)
        )
        return self.record(annotation_path, labels)

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
            names.extend(_create_ml_names(content))
        if include_external or content is None:
            try:
                with open(path, "r", encoding="utf8") as source:
                    names.extend(_create_ml_names(source.read()))
            except OSError:
                pass
        return tuple(dict.fromkeys(names))

    @staticmethod
    def validate_create_ml_resource(annotation_path):
        try:
            with open(
                annotation_path, "r", encoding="utf8"
            ) as source:
                records = json.load(source)
        except (OSError, UnicodeError, ValueError) as error:
            raise AnnotationDocumentError(
                "Could not parse CreateML JSON: %s" % error
            ) from error
        if not isinstance(records, list):
            raise AnnotationDocumentError(
                "CreateML JSON root must be a list"
            )
        for record in records:
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("image"), str)
                or not isinstance(record.get("annotations"), list)
            ):
                raise AnnotationDocumentError(
                    "CreateML record must contain image and annotations"
                )
            for annotation in record["annotations"]:
                coordinates = (
                    annotation.get("coordinates")
                    if isinstance(annotation, dict)
                    else None
                )
                if (
                    not isinstance(annotation, dict)
                    or not isinstance(annotation.get("label"), str)
                    or not isinstance(coordinates, dict)
                    or not all(
                        isinstance(coordinates.get(field), (int, float))
                        for field in ("x", "y", "width", "height")
                    )
                ):
                    raise AnnotationDocumentError(
                        "CreateML annotation is structurally invalid"
                    )
        return tuple(records)

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

    def delete(self, image_path, remover=move_to_recycle_bin):
        """Remove active-location annotations and update label discovery.

        File-list operations use AnnotationFileService for the broader
        both-location and shared-CreateML policy. This method remains as the
        recoverable compatibility boundary for workspace callers.
        """
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


def _create_ml_names(content):
    try:
        if isinstance(content, bytes):
            content = content.decode("utf8")
        records = json.loads(content)
    except (UnicodeError, ValueError, TypeError):
        return ()
    if not isinstance(records, list):
        return ()
    return tuple(
        os.path.basename(os.fspath(record.get("image")))
        for record in records
        if isinstance(record, dict) and record.get("image")
    )


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
