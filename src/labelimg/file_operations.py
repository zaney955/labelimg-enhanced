"""Annotation-aware filesystem operations for the file list."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import os
import platform
import shutil
import tempfile
import uuid
from xml.etree import ElementTree

from PyQt5.QtCore import QFile

from labelimg.annotation_storage import (
    MISSING_FINGERPRINT,
    fingerprint_path,
)
from labelimg.file_recovery import TrashIdentity, TrashedResource
from labelimg.create_ml_collection import (
    CreateMLAnnotationCollection,
    CreateMLCollectionError,
    CreateMLCollectionFormatError,
    CreateMLCollectionParseError,
    CreateMLRecordAmbiguous,
)


ANNOTATION_EXTENSIONS = (".xml", ".txt", ".json")


class FileOperationError(RuntimeError):
    pass


class _NullLease:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


@dataclass(frozen=True)
class OperationFailure:
    image_path: str
    path: str
    reason: str


@dataclass
class FileOperationResult:
    succeeded_images: list[str] = field(default_factory=list)
    failed_images: list[str] = field(default_factory=list)
    affected_paths: list[str] = field(default_factory=list)
    failures: list[OperationFailure] = field(default_factory=list)
    trashed_resources: list[TrashedResource] = field(default_factory=list)
    canceled: bool = False

    def add_failure(self, image_path, path, error):
        if image_path not in self.failed_images:
            self.failed_images.append(image_path)
        self.failures.append(
            OperationFailure(
                image_path=os.path.abspath(os.fspath(image_path)),
                path=os.path.abspath(os.fspath(path)),
                reason=str(error),
            )
        )

    def merge_trashed_resources(self, resources):
        """Keep one recovery identity per logical physical resource."""
        for resource in resources:
            key = os.path.normcase(
                os.path.abspath(resource.original_path)
            )
            existing_index = next(
                (
                    index
                    for index, existing in enumerate(
                        self.trashed_resources
                    )
                    if os.path.normcase(
                        os.path.abspath(existing.original_path)
                    ) == key
                ),
                None,
            )
            if existing_index is None:
                self.trashed_resources.append(resource)
            else:
                existing = self.trashed_resources[existing_index]
                self.trashed_resources[existing_index] = replace(
                    existing,
                    post_fingerprint=resource.post_fingerprint,
                )


def move_to_recycle_bin(path):
    path = os.path.abspath(os.fspath(path))
    if not os.path.lexists(path):
        return
    if platform.system() == "Windows":
        return _windows_move_to_recycle_bin(path)
    if not hasattr(QFile, "moveToTrash"):
        raise FileOperationError(
            "The system does not expose a recycle-bin operation."
        )
    return _qt_move_to_recycle_bin(path)


def _qt_move_to_recycle_bin(path):
    result = QFile.moveToTrash(path)
    succeeded = result[0] if isinstance(result, tuple) else result
    if not succeeded or os.path.lexists(path):
        raise FileOperationError(
            "The system recycle bin could not accept this path."
        )
    trash_path = (
        os.fspath(result[1])
        if isinstance(result, tuple)
        and len(result) > 1
        and result[1]
        else None
    )
    return TrashIdentity(
        backend="qt",
        token=trash_path,
        original_path=path,
        actionable=bool(trash_path),
    )


def _windows_move_to_recycle_bin(path):
    try:
        from labelimg.windows_trash import delete_to_recycle_bin
        token = delete_to_recycle_bin(path)
    except Exception as error:
        raise FileOperationError(
            "The Windows recycle bin could not accept this path: %s"
            % error
        ) from error
    if os.path.lexists(path) or token is None:
        raise FileOperationError(
            "The Windows recycle bin did not return a restorable item."
        )
    return TrashIdentity(
        backend="windows-shell",
        token=token,
        original_path=path,
        actionable=True,
    )


def _windows_restore_recycle_identity(token, destination):
    try:
        from labelimg.windows_trash import restore_recycle_item
        restore_recycle_item(token, destination)
    except Exception as error:
        raise FileOperationError(
            "The Windows recycle bin item could not be restored: %s"
            % error
        ) from error


class SystemTrashAdapter:
    def move(self, path):
        return move_to_recycle_bin(path)

    def exists(self, identity):
        if not identity.actionable:
            return False
        if identity.backend in ("qt", "path"):
            return bool(
                identity.token
                and os.path.lexists(os.fspath(identity.token))
            )
        if identity.backend == "windows-shell":
            try:
                from labelimg.windows_trash import recycle_item_exists
                return recycle_item_exists(identity.token)
            except Exception:
                return False
        return False

    def preflight(self, paths):
        paths = tuple(
            dict.fromkeys(
                os.path.abspath(os.fspath(path)) for path in paths
            )
        )
        try:
            if platform.system() == "Windows":
                from labelimg.windows_trash import probe_recycle_support
                for path in paths:
                    probe_recycle_support(path)
                return
            for directory in dict.fromkeys(
                os.path.dirname(path) for path in paths
            ):
                descriptor, probe = tempfile.mkstemp(
                    prefix=".labelimg-trash-probe-",
                    dir=directory,
                )
                os.close(descriptor)
                identity = None
                try:
                    identity = self.move(probe)
                    if (
                        identity is None
                        or not identity.actionable
                        or not self.exists(identity)
                    ):
                        raise FileOperationError(
                            "The system trash did not return a restorable "
                            "identity for the probe."
                        )
                    self.restore(identity, probe)
                finally:
                    if os.path.exists(probe):
                        os.remove(probe)
        except Exception as error:
            raise FileOperationError(
                "Recycle Bin preflight failed before any file was changed: %s"
                % error
            ) from error

    def restore(self, identity, destination):
        destination = os.path.abspath(os.fspath(destination))
        if os.path.lexists(destination):
            raise FileOperationError(
                "Recovery destination already exists: %s" % destination
            )
        if identity.backend in ("qt", "path"):
            source = os.fspath(identity.token)
            if not os.path.lexists(source):
                raise FileOperationError(
                    "Trash item is no longer available."
                )
            shutil.move(source, destination)
            return
        if identity.backend == "windows-shell":
            _windows_restore_recycle_identity(
                identity.token,
                destination,
            )
            return
        raise FileOperationError(
            "This trash entry cannot be restored automatically."
        )


def annotation_directories(image_path, save_dir=None):
    directories = [os.path.dirname(os.path.abspath(image_path))]
    if save_dir:
        directories.append(os.path.abspath(os.fspath(save_dir)))
    result = []
    seen = set()
    for directory in directories:
        key = os.path.normcase(directory)
        if key in seen:
            continue
        seen.add(key)
        result.append(directory)
    return tuple(result)


def exact_annotation_paths(image_path, save_dir=None):
    image_path = os.path.abspath(os.fspath(image_path))
    image_stem = os.path.splitext(os.path.basename(image_path))[0]
    paths = []
    for directory in annotation_directories(image_path, save_dir):
        stem = os.path.join(directory, image_stem)
        paths.extend(stem + extension for extension in ANNOTATION_EXTENSIONS)
    return tuple(paths)


class AnnotationFileService:
    def __init__(
        self,
        save_dir=None,
        trash=move_to_recycle_bin,
        storage_coordinator=None,
    ):
        self.save_dir = (
            os.path.abspath(os.fspath(save_dir))
            if save_dir
            else None
        )
        self.trash = trash
        self.storage_coordinator = storage_coordinator

    def clear_annotations(self, image_paths, should_continue=None):
        image_paths = tuple(
            os.path.abspath(os.fspath(path)) for path in image_paths
        )
        self._preflight_trash_operation(
            image_paths, include_images=False
        )
        result = FileOperationResult()
        for image_path in image_paths:
            if should_continue is not None and not should_continue():
                result.canceled = True
                break
            image_path = os.path.abspath(os.fspath(image_path))
            with self._stable_lease(image_path):
                affected, failures, trashed = (
                    self._clear_image_annotations(image_path)
                )
                if failures:
                    trashed, rollback_errors = self._rollback_trashed(
                        trashed
                    )
                    failures.extend(
                        (resource.original_path, error)
                        for resource, error in rollback_errors
                    )
                    if not rollback_errors:
                        affected = []
                    else:
                        affected = [
                            resource.original_path
                            for resource in trashed
                        ]
            result.affected_paths.extend(affected)
            result.merge_trashed_resources(trashed)
            for path, error in failures:
                result.add_failure(image_path, path, error)
            if not failures:
                result.succeeded_images.append(image_path)
        return result

    def delete_images(self, image_paths, should_continue=None):
        image_paths = tuple(
            os.path.abspath(os.fspath(path)) for path in image_paths
        )
        self._preflight_trash_operation(
            image_paths, include_images=True
        )
        result = FileOperationResult()
        for image_path in image_paths:
            if should_continue is not None and not should_continue():
                result.canceled = True
                break
            image_path = os.path.abspath(os.fspath(image_path))
            with self._stable_lease(image_path):
                affected, failures, trashed = (
                    self._clear_image_annotations(image_path)
                )
                if failures:
                    trashed, rollback_errors = self._rollback_trashed(
                        trashed
                    )
                    failures.extend(
                        (resource.original_path, error)
                        for resource, error in rollback_errors
                    )
                    if not rollback_errors:
                        affected = []
                    else:
                        affected = [
                            resource.original_path
                            for resource in trashed
                        ]
                    result.affected_paths.extend(affected)
                    result.merge_trashed_resources(trashed)
                    for path, error in failures:
                        result.add_failure(image_path, path, error)
                    continue
                try:
                    if not os.path.isfile(image_path):
                        raise FileOperationError(
                            "Image file does not exist."
                        )
                    identity = _trash_identity(
                        image_path,
                        self._move_to_trash(image_path),
                    )
                    image_resource = TrashedResource(
                        image_path,
                        identity,
                        MISSING_FINGERPRINT,
                    )
                    affected.append(image_path)
                    trashed.append(image_resource)
                    result.affected_paths.extend(affected)
                    result.merge_trashed_resources(trashed)
                    result.succeeded_images.append(image_path)
                except Exception as error:
                    trashed, rollback_errors = self._rollback_trashed(
                        trashed
                    )
                    if rollback_errors:
                        result.affected_paths.extend(
                            resource.original_path
                            for resource in trashed
                        )
                        result.merge_trashed_resources(trashed)
                        for resource, rollback_error in rollback_errors:
                            result.add_failure(
                                image_path,
                                resource.original_path,
                                rollback_error,
                            )
                    result.add_failure(image_path, image_path, error)
        return result

    def _move_to_trash(self, path):
        mover = getattr(self.trash, "move", None)
        return mover(path) if mover is not None else self.trash(path)

    def _restore_trash_identity(self, identity, destination):
        adapter = self.trash
        if not hasattr(adapter, "restore"):
            adapter = getattr(adapter, "__self__", None)
        if adapter is not None and hasattr(adapter, "restore"):
            adapter.restore(identity, destination)
            return
        if identity.backend in ("path", "qt") and identity.token:
            shutil.move(os.fspath(identity.token), destination)
            return
        SystemTrashAdapter().restore(identity, destination)

    def _rollback_trashed(self, resources):
        remaining = []
        errors = []
        for resource in reversed(tuple(resources)):
            temporary = None
            try:
                if os.path.lexists(resource.original_path):
                    temporary = _temporary_peer_path(
                        resource.original_path, "operation-rollback"
                    )
                    os.replace(resource.original_path, temporary)
                self._restore_trash_identity(
                    resource.identity,
                    resource.original_path,
                )
                if temporary is not None and os.path.lexists(temporary):
                    os.remove(temporary)
            except Exception as error:
                recovery_error = None
                if (
                    temporary is not None
                    and os.path.lexists(temporary)
                    and not os.path.lexists(resource.original_path)
                ):
                    try:
                        os.replace(temporary, resource.original_path)
                    except OSError as secondary_error:
                        recovery_error = secondary_error
                if _trash_identity_available(resource.identity, self.trash):
                    remaining.append(resource)
                detail = error
                if recovery_error is not None:
                    detail = FileOperationError(
                        "%s; restoring the displaced current file also "
                        "failed: %s" % (error, recovery_error)
                    )
                errors.append((resource, detail))
        remaining.reverse()
        return remaining, errors

    def _operation_resources(self, image_path, candidates):
        resources = list(
            exact_annotation_paths(image_path, self.save_dir)
        )
        resources.extend(candidates)
        resources.append(image_path)
        resources.extend(
            os.path.join(directory, "classes.txt")
            for directory in annotation_directories(
                image_path,
                self.save_dir,
            )
        )
        return tuple(dict.fromkeys(resources))

    @contextmanager
    def _stable_lease(self, image_path):
        if self.storage_coordinator is None:
            yield
            return
        for _attempt in range(5):
            candidates = self._annotation_candidates(image_path)
            locked_keys = {
                os.path.normcase(os.path.abspath(path))
                for path in candidates
            }
            lease = self.storage_coordinator.lease(
                self._operation_resources(image_path, candidates)
            )
            lease.__enter__()
            current = self._annotation_candidates(image_path)
            current_keys = {
                os.path.normcase(os.path.abspath(path))
                for path in current
            }
            if current_keys.issubset(locked_keys):
                try:
                    yield
                finally:
                    lease.__exit__(None, None, None)
                return
            lease.__exit__(None, None, None)
        raise FileOperationError(
            "Annotation resources kept changing while acquiring locks."
        )

    def _preflight_trash_operation(
        self, image_paths, include_images
    ):
        owner = getattr(self.trash, "__self__", None)
        preflight = getattr(owner, "preflight", None)
        if preflight is None:
            return
        paths = []
        for image_path in image_paths:
            paths.extend(
                path
                for path in self._annotation_candidates(image_path)
                if os.path.isfile(path)
            )
            if include_images and os.path.isfile(image_path):
                paths.append(image_path)
        preflight(paths)

    def annotation_count(self, image_paths):
        found = set()
        for image_path in image_paths:
            image_path = os.path.abspath(os.fspath(image_path))
            exact = {
                os.path.normcase(path)
                for path in exact_annotation_paths(
                    image_path,
                    self.save_dir,
                )
            }
            for path in self._annotation_candidates(image_path):
                if not os.path.isfile(path):
                    continue
                key = os.path.normcase(os.path.abspath(path))
                if key in exact and not path.lower().endswith(".json"):
                    found.add(key)
                    continue
                if not path.lower().endswith(".json"):
                    continue
                if os.path.getsize(path) == 0 and key in exact:
                    found.add(key)
                    continue
                try:
                    collection = CreateMLAnnotationCollection.read(path)
                except (
                    CreateMLCollectionParseError,
                    CreateMLCollectionFormatError,
                ):
                    if key in exact:
                        found.add(key)
                    continue
                if collection.contains_image(image_path):
                    found.add(key)
                elif not len(collection) and key in exact:
                    found.add(key)
        return len(found)

    def _clear_image_annotations(self, image_path):
        affected = []
        failures = []
        trashed = []
        exact = {
            os.path.normcase(os.path.abspath(path))
            for path in exact_annotation_paths(image_path, self.save_dir)
        }
        seen = set()
        for path in self._annotation_candidates(image_path):
            path = os.path.abspath(path)
            key = os.path.normcase(path)
            if key in seen or not os.path.isfile(path):
                continue
            seen.add(key)
            try:
                if not path.lower().endswith(".json"):
                    identity = _trash_identity(
                        path,
                        self._move_to_trash(path),
                    )
                    trashed.append(
                        TrashedResource(path, identity)
                    )
                    affected.append(path)
                    continue

                if os.path.getsize(path) == 0:
                    if key in exact:
                        identity = _trash_identity(
                            path,
                            self._move_to_trash(path),
                        )
                        trashed.append(
                            TrashedResource(path, identity)
                        )
                        affected.append(path)
                    continue

                try:
                    collection = CreateMLAnnotationCollection.read(path)
                except CreateMLCollectionFormatError:
                    if key in exact:
                        raise FileOperationError(
                            "The associated JSON is not a CreateML collection."
                        )
                    continue
                except CreateMLCollectionParseError as error:
                    raise FileOperationError(str(error)) from error
                try:
                    record = collection.resolve(
                        image_path, required=False
                    )
                except CreateMLRecordAmbiguous as error:
                    raise FileOperationError(
                        "The CreateML collection contains multiple matching "
                        "image records."
                    ) from error
                if record is None:
                    if key in exact and not len(collection):
                        identity = _trash_identity(
                            path,
                            self._move_to_trash(path),
                        )
                        trashed.append(
                            TrashedResource(path, identity)
                        )
                        affected.append(path)
                    elif key in exact:
                        raise FileOperationError(
                            "The associated CreateML collection has no "
                            "uniquely matching image record."
                        )
                    continue
                if len(collection) == 1:
                    identity = _trash_identity(
                        path,
                        self._move_to_trash(path),
                    )
                    trashed.append(
                        TrashedResource(path, identity)
                    )
                else:
                    retained = collection.remove_image(
                        image_path, required=True
                    )
                    identity = _recoverable_json_rewrite(
                        path,
                        retained.to_bytes(
                            ensure_ascii=False,
                            indent=2,
                        ),
                        self._move_to_trash,
                    )
                    trashed.append(
                        TrashedResource(
                            path,
                            _trash_identity(path, identity),
                            fingerprint_path(path),
                        )
                    )
                affected.append(path)
            except Exception as error:
                failures.append((path, error))
        return affected, failures, trashed

    def _annotation_candidates(self, image_path):
        candidates = list(
            exact_annotation_paths(image_path, self.save_dir)
        )
        for directory in annotation_directories(
            image_path,
            self.save_dir,
        ):
            try:
                names = os.listdir(directory)
            except OSError:
                continue
            candidates.extend(
                os.path.join(directory, name)
                for name in names
                if name.lower().endswith(".json")
            )
        return tuple(candidates)


class SynchronizedRenamer:
    def __init__(self, save_dir=None, storage_coordinator=None):
        self.save_dir = (
            os.path.abspath(os.fspath(save_dir))
            if save_dir
            else None
        )
        self.storage_coordinator = storage_coordinator
        self.last_fingerprints = {}
        self.last_resource_bytes = {}

    def rename(self, mapping):
        mapping = {
            os.path.abspath(os.fspath(source)):
            os.path.abspath(os.fspath(target))
            for source, target in mapping.items()
            if os.path.abspath(os.fspath(source))
            != os.path.abspath(os.fspath(target))
        }
        if not mapping:
            return {}
        for _attempt in range(5):
            json_paths = self._json_candidates(mapping)
            locked_json = {
                os.path.normcase(os.path.abspath(path))
                for path in json_paths
            }
            lease = (
                self.storage_coordinator.lease(
                    self._rename_resources(mapping) + list(json_paths)
                )
                if self.storage_coordinator is not None
                else _NullLease()
            )
            with lease:
                current_json = self._json_candidates(mapping)
                if not {
                    os.path.normcase(os.path.abspath(path))
                    for path in current_json
                }.issubset(locked_json):
                    continue
                self._validate_image_mapping(mapping)
                move_outputs, byte_outputs, sources = (
                    self._collect_outputs(mapping, json_paths)
                )
                self._validate_outputs(
                    move_outputs, byte_outputs, sources
                )
                self._execute_transaction(
                    move_outputs,
                    byte_outputs,
                    sources,
                )
                touched = set(sources)
                touched.update(move_outputs.values())
                touched.update(byte_outputs)
                touched.update(self._rename_resources(mapping))
                self.last_fingerprints = {
                    os.path.normcase(os.path.abspath(path)):
                    fingerprint_path(path)
                    for path in touched
                }
                self.last_resource_bytes = {}
                for path in touched:
                    key = os.path.normcase(os.path.abspath(path))
                    try:
                        with open(path, "rb") as source:
                            self.last_resource_bytes[key] = source.read()
                    except FileNotFoundError:
                        self.last_resource_bytes[key] = None
                return mapping
        raise FileOperationError(
            "Annotation resources kept changing while acquiring locks."
        )

    def _rename_resources(self, mapping):
        resources = []
        for source, target in mapping.items():
            resources.extend((source, target))
            resources.extend(
                exact_annotation_paths(source, self.save_dir)
            )
            resources.extend(
                exact_annotation_paths(target, self.save_dir)
            )
            resources.extend(
                os.path.join(directory, "classes.txt")
                for directory in annotation_directories(
                    source,
                    self.save_dir,
                )
            )
        return resources

    def _validate_image_mapping(self, mapping):
        targets = set()
        source_keys = {
            os.path.normcase(path) for path in mapping
        }
        for source, target in mapping.items():
            if not os.path.isfile(source):
                raise FileOperationError(
                    "Image file does not exist: %s" % source
                )
            if os.path.dirname(source) != os.path.dirname(target):
                raise FileOperationError(
                    "Renaming cannot move an image to another directory."
                )
            if (
                os.path.splitext(source)[1].casefold()
                != os.path.splitext(target)[1].casefold()
            ):
                raise FileOperationError(
                    "Renaming cannot change the image extension."
                )
            target_key = os.path.normcase(target)
            if target_key in targets:
                raise FileOperationError(
                    "Multiple images have the same target path: %s"
                    % target
                )
            targets.add(target_key)
            if os.path.exists(target) and target_key not in source_keys:
                raise FileOperationError(
                    "Target image already exists: %s" % target
                )

    def _collect_outputs(self, mapping, json_paths=None):
        move_outputs = {}
        byte_outputs = {}
        sources = set(mapping)
        source_owner = {}

        for source, target in mapping.items():
            move_outputs[source] = target
            old_stem = os.path.splitext(os.path.basename(source))[0]
            new_stem = os.path.splitext(os.path.basename(target))[0]
            for directory in annotation_directories(
                source,
                self.save_dir,
            ):
                for extension in (".xml", ".txt"):
                    annotation_source = os.path.join(
                        directory,
                        old_stem + extension,
                    )
                    if not os.path.isfile(annotation_source):
                        continue
                    self._claim_source(
                        source_owner,
                        annotation_source,
                        source,
                    )
                    annotation_target = os.path.join(
                        directory,
                        new_stem + extension,
                    )
                    sources.add(annotation_source)
                    if extension == ".txt":
                        move_outputs[annotation_source] = annotation_target
                    else:
                        byte_outputs[annotation_target] = (
                            _renamed_pascal_voc(
                                annotation_source,
                                target,
                            )
                        )

        if json_paths is None:
            json_paths = self._json_candidates(mapping)
        json_base_outputs = {}
        exact_owners = self._exact_json_owners(mapping)

        for json_path in json_paths:
            json_path = os.path.abspath(json_path)
            json_key = os.path.normcase(json_path)
            exact_owner = exact_owners.get(json_key)
            if not os.path.isfile(json_path):
                continue
            if os.path.getsize(json_path) == 0:
                if exact_owner is not None:
                    target = _renamed_annotation_path(
                        json_path,
                        mapping[exact_owner],
                    )
                    sources.add(json_path)
                    byte_outputs[target] = b""
                continue
            try:
                collection = CreateMLAnnotationCollection.read(
                    json_path
                )
            except CreateMLCollectionError as error:
                if exact_owner is not None:
                    if isinstance(
                        error, CreateMLCollectionFormatError
                    ):
                        raise FileOperationError(
                            "Associated JSON is not a CreateML collection: %s"
                            % json_path
                        ) from error
                    raise FileOperationError(str(error)) from error
                continue
            try:
                plan = collection.plan_rename(
                    mapping,
                    exact_owner=exact_owner,
                )
            except CreateMLCollectionError as error:
                raise FileOperationError(str(error)) from error
            if not plan.changed:
                continue

            sources.add(json_path)
            if plan.source is not None:
                json_base_outputs[json_path] = plan.source
            for target, contribution in plan.targets:
                existing = json_base_outputs.get(
                    target,
                    CreateMLAnnotationCollection.empty(target),
                )
                try:
                    json_base_outputs[target] = existing.merge(
                        contribution
                    )
                except CreateMLCollectionError as error:
                    raise FileOperationError(str(error)) from error

        for path, collection in json_base_outputs.items():
            byte_outputs[path] = collection.to_bytes(
                ensure_ascii=False,
                indent=2,
            )

        return move_outputs, byte_outputs, sources

    def _validate_outputs(self, move_outputs, byte_outputs, sources):
        source_keys = {os.path.normcase(path) for path in sources}
        output_keys = {}
        for target in list(move_outputs.values()) + list(byte_outputs):
            key = os.path.normcase(target)
            if key in output_keys:
                raise FileOperationError(
                    "Multiple artifacts have the same target path: %s"
                    % target
                )
            output_keys[key] = target
            if os.path.exists(target) and key not in source_keys:
                raise FileOperationError(
                    "Target artifact already exists: %s" % target
                )

    def _execute_transaction(self, move_outputs, byte_outputs, sources):
        staged = {}
        created_targets = []
        moved_target_sources = {}
        try:
            for source in sorted(sources, key=str.casefold):
                temporary = _temporary_peer_path(source, "rename")
                os.replace(source, temporary)
                staged[source] = temporary

            for source, target in move_outputs.items():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(staged[source], target)
                created_targets.append(target)
                moved_target_sources[target] = source

            for target, content in byte_outputs.items():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                _atomic_write_bytes(target, content)
                created_targets.append(target)

            for temporary in staged.values():
                if os.path.exists(temporary):
                    os.remove(temporary)
        except Exception as error:
            rollback_failures = self._rollback(
                staged,
                created_targets,
                moved_target_sources,
            )
            message = str(error)
            if rollback_failures:
                message += "; rollback failures: " + "; ".join(
                    rollback_failures
                )
            raise FileOperationError(message) from error

    @staticmethod
    def _rollback(staged, created_targets, moved_target_sources):
        displaced = {}
        failures = []
        for target in reversed(created_targets):
            if not os.path.exists(target):
                continue
            try:
                temporary = _temporary_peer_path(target, "rollback")
                os.replace(target, temporary)
                displaced[target] = temporary
            except Exception as error:
                failures.append("%s (%s)" % (target, error))

        for source, temporary in staged.items():
            if not os.path.exists(temporary):
                continue
            try:
                os.replace(temporary, source)
            except Exception as error:
                failures.append("%s (%s)" % (source, error))

        for target, source in moved_target_sources.items():
            temporary = displaced.pop(target, None)
            if temporary is None or not os.path.exists(temporary):
                continue
            try:
                os.replace(temporary, source)
            except Exception as error:
                failures.append("%s (%s)" % (source, error))

        for temporary in displaced.values():
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        return failures

    def _json_candidates(self, mapping):
        paths = set()
        for source in mapping:
            old_stem = os.path.splitext(os.path.basename(source))[0]
            for directory in annotation_directories(
                source,
                self.save_dir,
            ):
                paths.add(os.path.join(directory, old_stem + ".json"))
                try:
                    names = os.listdir(directory)
                except OSError:
                    continue
                paths.update(
                    os.path.join(directory, name)
                    for name in names
                    if name.lower().endswith(".json")
                )
        return tuple(sorted(paths, key=str.casefold))

    def _exact_json_owners(self, mapping):
        owners = {}
        for source in mapping:
            old_stem = os.path.splitext(os.path.basename(source))[0]
            for directory in annotation_directories(
                source,
                self.save_dir,
            ):
                path = os.path.normcase(
                    os.path.join(directory, old_stem + ".json")
                )
                if path in owners and owners[path] != source:
                    raise FileOperationError(
                        "Multiple images claim the same CreateML path: %s"
                        % path
                    )
                owners[path] = source
        return owners

    @staticmethod
    def _basename_mapping(mapping):
        result = {}
        for source in mapping:
            key = os.path.basename(source).casefold()
            if key in result and result[key] != source:
                raise FileOperationError(
                    "CreateML records are ambiguous for duplicate image "
                    "name: %s" % os.path.basename(source)
                )
            result[key] = source
        return result

    @staticmethod
    def _claim_source(claims, path, owner):
        key = os.path.normcase(os.path.abspath(path))
        previous = claims.get(key)
        if previous is not None and previous != owner:
            raise FileOperationError(
                "Multiple images claim the same annotation path: %s"
                % path
            )
        claims[key] = owner


def _trash_identity_available(identity, trash):
    owner = trash if hasattr(trash, "exists") else getattr(
        trash, "__self__", None
    )
    if owner is not None and hasattr(owner, "exists"):
        try:
            return bool(owner.exists(identity))
        except Exception:
            return True
    if identity.backend in ("path", "qt") and identity.token:
        return os.path.lexists(os.fspath(identity.token))
    return True


def _recoverable_json_rewrite(path, content, trash):
    directory = os.path.dirname(path)
    temporary = _write_temporary_bytes(directory, content)
    backup = _temporary_peer_path(path, "backup")
    trash_result = None
    try:
        shutil.copy2(path, backup)
        trash_result = trash(path)
        os.replace(temporary, path)
        temporary = None
    except Exception:
        if not os.path.exists(path) and os.path.exists(backup):
            os.replace(backup, path)
        raise
    finally:
        for candidate in (temporary, backup):
            if candidate and os.path.exists(candidate):
                try:
                    os.remove(candidate)
                except OSError:
                    pass
    return trash_result


def _trash_identity(original_path, result):
    if isinstance(result, TrashIdentity):
        return result
    if result:
        return TrashIdentity(
            backend="path",
            token=os.fspath(result),
            original_path=os.path.abspath(original_path),
            actionable=True,
        )
    return TrashIdentity(
        backend="manual",
        token=None,
        original_path=os.path.abspath(original_path),
        actionable=False,
    )


def _renamed_pascal_voc(annotation_path, new_image_path):
    try:
        tree = ElementTree.parse(annotation_path)
        root = tree.getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise FileOperationError(
            "Could not parse Pascal VOC XML %s: %s"
            % (annotation_path, error)
        ) from error
    filename = root.find("filename")
    if filename is None:
        filename = ElementTree.SubElement(root, "filename")
    filename.text = os.path.basename(new_image_path)
    path = root.find("path")
    if path is not None:
        path.text = os.path.abspath(new_image_path)
    return ElementTree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
    )


def _renamed_annotation_path(annotation_path, new_image_path):
    return os.path.join(
        os.path.dirname(annotation_path),
        os.path.splitext(os.path.basename(new_image_path))[0]
        + os.path.splitext(annotation_path)[1],
    )


def _temporary_peer_path(path, purpose):
    directory = os.path.dirname(os.path.abspath(path))
    basename = os.path.basename(path)
    while True:
        candidate = os.path.join(
            directory,
            ".%s.labelimg-%s-%s"
            % (basename, purpose, uuid.uuid4().hex),
        )
        if not os.path.lexists(candidate):
            return candidate


def _write_temporary_bytes(directory, content):
    descriptor, path = tempfile.mkstemp(
        prefix=".labelimg-",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if os.path.exists(path):
            os.remove(path)
        raise
    return path


def _atomic_write_bytes(path, content):
    temporary = _write_temporary_bytes(
        os.path.dirname(os.path.abspath(path)),
        content,
    )
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
