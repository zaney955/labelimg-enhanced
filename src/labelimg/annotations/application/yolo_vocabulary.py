"""Plan append-only class IDs across one annotation workspace."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from labelimg.annotations.domain.model import AnnotationDocumentError, YoloWorkspaceMappingConflict
from labelimg.annotations.infrastructure.formats.yolo_classes import decode_yolo_classes, resolve_yolo_classes, yolo_dataset_root
from labelimg.annotations.infrastructure.storage import MISSING_FINGERPRINT, ResourceFingerprint


def shared_yolo_classes_path(annotation_path, save_dir=None, image_dir=None):
    directory = Path(annotation_path).absolute().parent
    selected = Path(save_dir or image_dir).absolute() if save_dir or image_dir else directory
    root = selected if directory.is_relative_to(selected) else directory
    for parent in (directory, *directory.parents):
        if parent.name.casefold() == "labels":
            root = parent
            break
    return str(root / "classes.txt")


@dataclass(frozen=True)
class YoloVocabularyPlan:
    names: tuple
    shared_path: str
    fingerprints: tuple


def plan_yolo_vocabulary(annotation_path, *, save_dir=None, image_dir=None, reserved=(), labels=()):
    shared = shared_yolo_classes_path(annotation_path, save_dir, image_dir)
    root = Path(shared).parent
    boundary = root.resolve()
    paths = {shared, str(Path(annotation_path).absolute().parent / "classes.txt")}
    for directory, children, filenames in os.walk(root):
        children[:] = sorted(
            child for child in children
            if not child.startswith(".labelimg-")
            and (Path(directory) / child).resolve().is_relative_to(boundary)
        )
        paths.update(str(Path(directory) / name) for name in filenames if name.casefold() == "classes.txt")

    contents = {}
    fingerprints = {}

    def read(path):
        path = os.path.abspath(path)
        if path not in contents:
            try:
                stat = os.stat(path)
                with open(path, "rb") as source:
                    content = source.read()
            except FileNotFoundError:
                content = None
                fingerprint = MISSING_FINGERPRINT
            else:
                fingerprint = ResourceFingerprint(
                    exists=True, size=len(content), modified_ns=stat.st_mtime_ns,
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            contents[path] = content
            fingerprints[path] = fingerprint
        return contents[path]

    mappings = []
    for path in sorted(paths, key=lambda value: (value.casefold(), value)):
        if not Path(path).resolve().is_relative_to(boundary):
            raise AnnotationDocumentError("Class mapping is outside the annotation workspace: %s" % path)
        content = read(path)
        if content is not None:
            names = tuple(decode_yolo_classes(content))
            if len(set(names)) != len(names):
                raise AnnotationDocumentError("%s: class names must be unique" % path)
            if names:
                mappings.append((path, names))
    # Resolve legacy/YAML sources too, but do not rewrite their configuration.
    mapping = resolve_yolo_classes(
        annotation_path, allow_missing=True, read_content=read,
        dataset_root=yolo_dataset_root(annotation_path, save_dir or image_dir),
    )
    if mapping.names and not any(path == mapping.source for path, _ in mappings):
        mappings.append((mapping.source, mapping.names))
    if mappings:
        source, canonical = max(mappings, key=lambda item: len(item[1]))
        for path, names in mappings:
            for index, (expected, actual) in enumerate(zip(canonical, names)):
                if expected != actual:
                    raise YoloWorkspaceMappingConflict(source, path, index, expected, actual)
    else:
        canonical = ()
    result = list(canonical)
    for name in (*reserved, *labels):
        name = str(name).strip()
        if name and name not in result:
            result.append(name)
    return YoloVocabularyPlan(tuple(result), shared, tuple(fingerprints.items()))
