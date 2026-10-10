"""Resolve YOLO class IDs without changing their dataset order."""

from dataclasses import dataclass
import codecs
import locale
import hashlib
from pathlib import Path

import yaml

from labelimg.annotations.domain.model import (
    AnnotationDocumentError,
    YoloClassMappingError,
)

ENCODE_METHOD = "utf-8"


def decode_yolo_classes(content):
    """Decode UTF-8 classes, including files written by legacy locale I/O."""
    if isinstance(content, str):
        text = content
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as utf8_error:
            legacy_encoding = locale.getpreferredencoding(False)
            try:
                is_utf8 = (
                    codecs.lookup(legacy_encoding).name
                    == codecs.lookup(ENCODE_METHOD).name
                )
            except LookupError:
                raise utf8_error
            if is_utf8:
                raise utf8_error
            try:
                text = content.decode(legacy_encoding)
            except LookupError, UnicodeDecodeError:
                raise utf8_error
    return [line.strip() for line in text.splitlines() if line.strip()]


@dataclass(frozen=True)
class YoloClasses:
    names: tuple
    source: str | None
    resources: tuple
    dataset_root: str = ""
    requires_confirmation: bool = False
    content_digest: str = ""


def yolo_dataset_root(annotation_path, annotation_dir=None):
    """Use the conventional dataset boundary, or the selected flat directory."""
    directory = Path(annotation_path).absolute().parent
    for parent in (directory, *directory.parents):
        if parent.name.casefold() in {"labels", "images"}:
            return parent.parent
    if annotation_dir is not None:
        selected = Path(annotation_dir).absolute()
        if directory.is_relative_to(selected):
            return selected
    return directory


def recommended_yolo_class_paths(annotation_path, dataset_root=None):
    directory = Path(annotation_path).absolute().parent
    root = (
        Path(dataset_root)
        if dataset_root is not None
        else yolo_dataset_root(annotation_path)
    )
    paths = [directory / "classes.txt"]
    labels = root / "labels"
    if directory.is_relative_to(labels) and directory != labels:
        paths.append(labels / "classes.txt")
    paths.append(root / "data.yaml")
    return tuple(str(p) for p in paths)


def yolo_class_candidates(annotation_path, dataset_root=None):
    """Recommended locations first; legacy ancestor locations stay in the dataset."""
    directory = Path(annotation_path).absolute().parent
    root = (
        Path(dataset_root)
        if dataset_root is not None
        else yolo_dataset_root(annotation_path)
    )
    candidates = list(recommended_yolo_class_paths(annotation_path, root))
    if directory.is_relative_to(root):
        for parent in (directory, *directory.parents):
            for name in ("classes.txt", "data.yaml"):
                path = str(parent / name)
                if path not in candidates:
                    candidates.append(path)
            if parent == root:
                break
    # Also exclude symlinks/junctions whose configuration points outside the dataset.
    boundary = root.resolve()
    return tuple(p for p in candidates if Path(p).resolve().is_relative_to(boundary))


def read_class_content(path):
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        keys = [self.construct_object(key, deep=deep) for key, _value in node.value]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate YAML mapping keys")
        return mapping


def _yaml_names(content, path):
    try:
        data = yaml.load(content.decode("utf-8-sig"), Loader=_UniqueKeyLoader)
        names = data.get("names") if isinstance(data, dict) else None
        if isinstance(names, dict):
            indexed = {}
            for key, value in names.items():
                if isinstance(key, bool) or not isinstance(key, (int, str)):
                    raise ValueError("class IDs must be nonnegative integers")
                index = int(key)
                if str(index) != str(key) or index in indexed:
                    raise ValueError("class IDs must be unique integers")
                indexed[index] = value
            if set(indexed) != set(range(len(indexed))):
                raise ValueError("class IDs must be contiguous starting at zero")
            names = [indexed[i] for i in range(len(indexed))]
        if not isinstance(names, list) or not names:
            raise ValueError("names must be a nonempty list or ID mapping")
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("class names must be nonempty strings")
        names = [name.strip() for name in names]
        if len(set(names)) != len(names):
            raise ValueError("class names must be unique")
        return names
    except (UnicodeError, ValueError, yaml.YAMLError) as error:
        raise AnnotationDocumentError("%s: %s" % (path, error)) from error


def missing_yolo_classes(annotation_path, checked_paths=(), *, line_number=None):
    paths = list(checked_paths or yolo_class_candidates(annotation_path))
    if not any(Path(path).name.casefold() == "data.yaml" for path in paths):
        directory = Path(annotation_path).absolute().parent
        labels_root = next(
            (
                p
                for p in (directory, *directory.parents)
                if p.name.casefold() == "labels"
            ),
            None,
        )
        dataset_root = labels_root.parent if labels_root is not None else directory
        paths.append(str(dataset_root / "data.yaml"))
    return YoloClassMappingError(
        "missing", annotation_path, line_number=line_number, checked_paths=paths
    )


def resolve_yolo_classes(
    annotation_path,
    *,
    read_content=None,
    allow_missing=False,
    candidates=None,
    dataset_root=None,
):
    read_content = read_content or read_class_content
    root = (
        Path(dataset_root)
        if dataset_root is not None
        else yolo_dataset_root(annotation_path)
    )
    recommended = recommended_yolo_class_paths(annotation_path, root)
    resources = []
    for path in (
        candidates
        if candidates is not None
        else yolo_class_candidates(annotation_path, root)
    ):
        resources.append(path)
        content = read_content(path)
        if content is None:
            continue
        try:
            names = (
                _yaml_names(content, path)
                if Path(path).suffix.casefold() == ".yaml"
                else decode_yolo_classes(content)
            )
        except UnicodeError as error:
            raise AnnotationDocumentError("%s: %s" % (path, error)) from error
        if names:
            if len(set(names)) != len(names):
                raise AnnotationDocumentError("%s: class names must be unique" % path)
            return YoloClasses(
                tuple(names),
                path,
                tuple(resources),
                str(root),
                path not in recommended,
                hashlib.sha256(content).hexdigest(),
            )
    if allow_missing:
        return YoloClasses((), None, tuple(resources), str(root))
    raise missing_yolo_classes(annotation_path, resources)
