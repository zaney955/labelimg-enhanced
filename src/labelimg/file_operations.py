"""Annotation-aware filesystem operations for the file list."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import json
import os
import platform
import shutil
import tempfile
import uuid
from xml.etree import ElementTree

from PyQt5.QtCore import QFile


ANNOTATION_EXTENSIONS = (".xml", ".txt", ".json")


class FileOperationError(RuntimeError):
    pass


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


def move_to_recycle_bin(path):
    path = os.path.abspath(os.fspath(path))
    if not os.path.lexists(path):
        return
    if platform.system() == "Windows":
        _windows_move_to_recycle_bin(path)
        return
    if not hasattr(QFile, "moveToTrash"):
        raise FileOperationError(
            "The system does not expose a recycle-bin operation."
        )
    result = QFile.moveToTrash(path)
    succeeded = result[0] if isinstance(result, tuple) else result
    if not succeeded or os.path.lexists(path):
        raise FileOperationError(
            "The system recycle bin could not accept this path."
        )


def _windows_move_to_recycle_bin(path):
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", ctypes.c_bool),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    operation = SHFILEOPSTRUCTW()
    operation.wFunc = 3  # FO_DELETE
    operation.pFrom = path + "\0"
    operation.pTo = None
    operation.fFlags = (
        0x0040  # FOF_ALLOWUNDO
        | 0x0010  # FOF_NOCONFIRMATION
        | 0x0004  # FOF_SILENT
        | 0x0400  # FOF_NOERRORUI
    )
    result = ctypes.windll.shell32.SHFileOperationW(
        ctypes.byref(operation)
    )
    if (
        result != 0
        or operation.fAnyOperationsAborted
        or os.path.lexists(path)
    ):
        raise FileOperationError(
            "The Windows recycle bin could not accept this path "
            "(error %s)." % result
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
    def __init__(self, save_dir=None, trash=move_to_recycle_bin):
        self.save_dir = (
            os.path.abspath(os.fspath(save_dir))
            if save_dir
            else None
        )
        self.trash = trash

    def clear_annotations(self, image_paths, should_continue=None):
        result = FileOperationResult()
        for image_path in image_paths:
            if should_continue is not None and not should_continue():
                result.canceled = True
                break
            image_path = os.path.abspath(os.fspath(image_path))
            affected, failures = self._clear_image_annotations(image_path)
            result.affected_paths.extend(affected)
            for path, error in failures:
                result.add_failure(image_path, path, error)
            if not failures:
                result.succeeded_images.append(image_path)
        return result

    def delete_images(self, image_paths, should_continue=None):
        result = FileOperationResult()
        for image_path in image_paths:
            if should_continue is not None and not should_continue():
                result.canceled = True
                break
            image_path = os.path.abspath(os.fspath(image_path))
            affected, failures = self._clear_image_annotations(image_path)
            result.affected_paths.extend(affected)
            for path, error in failures:
                result.add_failure(image_path, path, error)
            if failures:
                continue
            try:
                if not os.path.isfile(image_path):
                    raise FileOperationError("Image file does not exist.")
                self.trash(image_path)
                result.affected_paths.append(image_path)
                result.succeeded_images.append(image_path)
            except Exception as error:
                result.add_failure(image_path, image_path, error)
        return result

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
                    entries = _read_create_ml_collection(path)
                except FileOperationError:
                    if key in exact:
                        found.add(key)
                    continue
                if entries is None:
                    continue
                if _matching_create_ml_indices(
                    entries,
                    os.path.basename(image_path),
                ):
                    found.add(key)
                elif not entries and key in exact:
                    found.add(key)
        return len(found)

    def _clear_image_annotations(self, image_path):
        affected = []
        failures = []
        exact = {
            os.path.normcase(os.path.abspath(path))
            for path in exact_annotation_paths(image_path, self.save_dir)
        }
        basename = os.path.basename(image_path)
        seen = set()
        for path in self._annotation_candidates(image_path):
            path = os.path.abspath(path)
            key = os.path.normcase(path)
            if key in seen or not os.path.isfile(path):
                continue
            seen.add(key)
            try:
                if not path.lower().endswith(".json"):
                    self.trash(path)
                    affected.append(path)
                    continue

                if os.path.getsize(path) == 0:
                    if key in exact:
                        self.trash(path)
                        affected.append(path)
                    continue

                entries = _read_create_ml_collection(path)
                if entries is None:
                    if key in exact:
                        raise FileOperationError(
                            "The associated JSON is not a CreateML collection."
                        )
                    continue
                matches = _matching_create_ml_indices(entries, basename)
                if len(matches) > 1:
                    raise FileOperationError(
                        "The CreateML collection contains multiple matching "
                        "image records."
                    )
                if not matches:
                    if key in exact and not entries:
                        self.trash(path)
                        affected.append(path)
                    elif key in exact:
                        raise FileOperationError(
                            "The associated CreateML collection has no "
                            "uniquely matching image record."
                        )
                    continue
                if len(entries) == 1:
                    self.trash(path)
                else:
                    retained = [
                        entry
                        for index, entry in enumerate(entries)
                        if index != matches[0]
                    ]
                    _recoverable_json_rewrite(
                        path,
                        retained,
                        self.trash,
                    )
                affected.append(path)
            except Exception as error:
                failures.append((path, error))
        return affected, failures

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
    def __init__(self, save_dir=None):
        self.save_dir = (
            os.path.abspath(os.fspath(save_dir))
            if save_dir
            else None
        )

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
        self._validate_image_mapping(mapping)
        move_outputs, byte_outputs, sources = self._collect_outputs(
            mapping
        )
        self._validate_outputs(move_outputs, byte_outputs, sources)
        self._execute_transaction(move_outputs, byte_outputs, sources)
        return mapping

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

    def _collect_outputs(self, mapping):
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

        json_paths = self._json_candidates(mapping)
        json_base_outputs = {}
        json_contributions = {}
        basename_mapping = self._basename_mapping(mapping)
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
                entries = _read_create_ml_collection(json_path)
            except FileOperationError:
                if exact_owner is not None:
                    raise
                continue
            if entries is None:
                if exact_owner is not None:
                    raise FileOperationError(
                        "Associated JSON is not a CreateML collection: %s"
                        % json_path
                    )
                continue

            matched = []
            updated_entries = []
            counts = {}
            for entry in entries:
                image_name = entry.get("image") if isinstance(entry, dict) else None
                key = (
                    os.path.basename(os.fspath(image_name)).casefold()
                    if image_name
                    else None
                )
                owner = basename_mapping.get(key)
                if owner is None:
                    updated_entries.append(entry)
                    continue
                counts[owner] = counts.get(owner, 0) + 1
                changed = dict(entry)
                changed["image"] = os.path.basename(mapping[owner])
                matched.append((owner, changed))

            duplicate_owner = next(
                (owner for owner, count in counts.items() if count > 1),
                None,
            )
            if duplicate_owner is not None:
                raise FileOperationError(
                    "CreateML collection has multiple records for %s: %s"
                    % (os.path.basename(duplicate_owner), json_path)
                )
            if not matched:
                if exact_owner is not None and entries:
                    raise FileOperationError(
                        "Associated CreateML collection has no matching "
                        "record: %s" % json_path
                    )
                continue

            sources.add(json_path)
            if exact_owner is None:
                rewritten = []
                replacements = {
                    owner: entry for owner, entry in matched
                }
                for entry in entries:
                    image_name = entry.get("image") if isinstance(entry, dict) else None
                    key = (
                        os.path.basename(os.fspath(image_name)).casefold()
                        if image_name
                        else None
                    )
                    owner = basename_mapping.get(key)
                    rewritten.append(
                        replacements.get(owner, entry)
                    )
                json_base_outputs[json_path] = rewritten
                continue

            if len(entries) == 1 and len(matched) == 1:
                owner, changed = matched[0]
                target = _renamed_annotation_path(
                    json_path,
                    mapping[owner],
                )
                json_contributions.setdefault(target, []).append(changed)
                continue

            if updated_entries:
                json_base_outputs[json_path] = updated_entries
            for owner, changed in matched:
                target = _renamed_annotation_path(
                    json_path,
                    mapping[owner],
                )
                json_contributions.setdefault(target, []).append(changed)

        for path, entries in json_contributions.items():
            existing = json_base_outputs.setdefault(path, [])
            existing_names = {
                os.path.basename(entry.get("image", "")).casefold()
                for entry in existing
                if isinstance(entry, dict)
            }
            for entry in entries:
                name = os.path.basename(entry.get("image", "")).casefold()
                if name in existing_names:
                    raise FileOperationError(
                        "CreateML target already contains image %s: %s"
                        % (entry.get("image"), path)
                    )
                existing_names.add(name)
                existing.append(entry)

        for path, entries in json_base_outputs.items():
            byte_outputs[path] = _json_bytes(entries)

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


def _read_create_ml_collection(path):
    try:
        with open(path, "r", encoding="utf8") as source:
            value = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FileOperationError(
            "Could not parse CreateML JSON %s: %s" % (path, error)
        ) from error
    if not isinstance(value, list):
        return None
    if not all(isinstance(entry, dict) for entry in value):
        return None
    if value and not all("image" in entry for entry in value):
        return None
    return value


def _matching_create_ml_indices(entries, image_name):
    expected = os.path.basename(image_name).casefold()
    return [
        index
        for index, entry in enumerate(entries)
        if os.path.basename(
            os.fspath(entry.get("image", ""))
        ).casefold() == expected
    ]


def _recoverable_json_rewrite(path, entries, trash):
    directory = os.path.dirname(path)
    temporary = _write_temporary_bytes(directory, _json_bytes(entries))
    backup = _temporary_peer_path(path, "backup")
    try:
        shutil.copy2(path, backup)
        trash(path)
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


def _json_bytes(entries):
    return json.dumps(
        entries,
        ensure_ascii=False,
        indent=2,
    ).encode("utf8")


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
