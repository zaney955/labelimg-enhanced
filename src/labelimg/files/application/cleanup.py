"""Read-only cleanup plans for the selected image/annotation directory pair."""

from dataclasses import dataclass, field
import math
import os
from xml.etree import ElementTree

from labelimg.annotations import (
    CreateMLAnnotationCollection, CreateMLRecordIdentity,
    annotation_stems_for_image, fingerprint_path,
)
from labelimg.files.application.operations import FileOperationError


def path_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


class CleanupError(FileOperationError):
    def __init__(self, reason, path=""):
        self.reason = reason
        self.path = os.fspath(path)
        super().__init__(reason + (": " + self.path if self.path else ""))


class CleanupCanceled(Exception):
    pass


@dataclass(frozen=True)
class CleanupItem:
    path: str
    reason: str
    fingerprint: object
    image_paths: tuple = ()


@dataclass(frozen=True)
class CleanupPlan:
    image_dir: str
    annotation_dir: str
    extensions: tuple
    items: tuple
    skipped: tuple
    image_paths: tuple
    scan_directories: tuple


@dataclass
class CleanupResult:
    removed_paths: list = field(default_factory=list)
    affected_images: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    trashed_resources: list = field(default_factory=list)
    canceled: bool = False


def verify_cleanup_item(plan, item):
    if _linked(item.path) or not _inside(item.path, plan.annotation_dir) or fingerprint_path(item.path) != item.fingerprint:
        raise CleanupError("changed", item.path)


def _inside(path, root):
    try:
        return os.path.commonpath((os.path.realpath(path), os.path.realpath(root))) == os.path.realpath(root)
    except ValueError:
        return False


def _linked(path):
    return os.path.islink(path) or os.path.isjunction(path)


def _walk(directory, report=None, *, recursive=True):
    def failed(error):
        raise error

    for current, directories, filenames in os.walk(directory, onerror=failed):
        directories[:] = sorted(
            name for name in directories
            if recursive and not _linked(os.path.join(current, name))
            and _inside(os.path.join(current, name), directory)
        )
        if report:
            report(current)
        for name in sorted(filenames):
            path = os.path.join(current, name)
            if report:
                report(path)
            if not _linked(path) and _inside(path, directory):
                yield path


def cleanup_scan_directories(image_dir, annotation_dir):
    """Limit labels-root scans to the opened conventional image split."""
    if os.path.basename(annotation_dir).casefold() == "labels":
        ancestor = image_dir
        while True:
            if os.path.basename(ancestor).casefold() == "images":
                relative = os.path.relpath(image_dir, ancestor)
                if relative != ".":
                    return ((os.path.join(annotation_dir, relative), True), (annotation_dir, False))
                break
            parent = os.path.dirname(ancestor)
            if parent == ancestor:
                break
            ancestor = parent
    return ((annotation_dir, True),)


def _image_index(image_dir, annotation_dir, extensions, report):
    images = tuple(
        path for path in _walk(image_dir, report)
        if os.path.splitext(path)[1].casefold() in extensions
    )
    by_stem, by_name = {}, {}
    for image in images:
        for stem in annotation_stems_for_image(image, annotation_dir, image_dir):
            by_stem.setdefault(path_key(stem), []).append(image)
        by_name.setdefault(os.path.basename(image).casefold(), []).append(image)
    return images, by_stem, by_name


def _inspect(path, content, mapped_images, by_name):
    """Return empty reason plus associations; invalid data raises ValueError."""
    if not content:
        return "zeroBytes", mapped_images
    text = content.decode("utf-8-sig")
    if not text.strip():
        return "whitespace", mapped_images
    extension = os.path.splitext(path)[1].casefold()
    if extension == ".xml":
        root = ElementTree.fromstring(content)
        if root.tag != "annotation":
            raise ValueError("Not a Pascal VOC annotation")
        objects = root.findall("object")
        for item in objects:
            if not item.findtext("name", "").strip():
                raise ValueError("Missing object name")
            for field in ("xmin", "ymin", "xmax", "ymax"):
                if not math.isfinite(float(item.findtext("bndbox/" + field, ""))):
                    raise ValueError("Invalid bounding box")
        return ("noObjects" if not objects else ""), mapped_images
    if extension == ".txt":
        rows = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        for row in rows:
            fields = row.split()
            if len(fields) != 5 or int(fields[0]) < 0 or not all(math.isfinite(float(value)) for value in fields[1:]):
                raise ValueError("Not a YOLO detection annotation")
        return ("noObjects" if not rows else ""), mapped_images
    collection = CreateMLAnnotationCollection.read(path, content=content, strict=True)
    matches = set()
    for record in collection.records:
        # Single, short, same-stem references use workspace directory mapping.
        reference = record.reference.replace("\\", "/")
        if len(collection.records) == 1 and "/" not in reference and os.path.splitext(reference)[0].casefold() == os.path.splitext(os.path.basename(path))[0].casefold():
            matches.update(image for image in mapped_images if record.identity.matches(image))
        else:
            name = reference.rsplit("/", 1)[-1].casefold()
            identity = CreateMLRecordIdentity(path, record.reference)
            matches.update(image for image in by_name.get(name, ()) if identity.matches(image))
    # Collections with no records have only the filename mapping available.
    if not collection.records:
        matches.update(mapped_images)
    return ("noObjects" if not collection.has_annotations else ""), tuple(sorted(matches))


def scan_cleanup(image_dir, annotation_dir, extensions, report=None):
    image_dir, annotation_dir = os.path.abspath(image_dir), os.path.abspath(annotation_dir)
    if not os.path.isdir(image_dir) or not os.path.isdir(annotation_dir):
        raise CleanupError("directories")
    extensions = tuple(value.casefold() if value.startswith(".") else "." + value.casefold() for value in extensions)
    images, by_stem, by_name = _image_index(image_dir, annotation_dir, extensions, report)
    scopes = cleanup_scan_directories(image_dir, annotation_dir)
    items, skipped, seen = [], [], set()
    for directory, recursive in scopes:
        if not os.path.isdir(directory) or _linked(directory) or not _inside(directory, annotation_dir):
            continue
        for path in _walk(directory, report, recursive=recursive):
            if path_key(path) in seen or os.path.splitext(path)[1].casefold() not in (".xml", ".txt", ".json"):
                continue
            seen.add(path_key(path))
            if os.path.basename(path).casefold() in ("classes.txt", "predefined_classes.txt"):
                continue
            try:
                before = fingerprint_path(path)
                with open(path, "rb") as source:
                    content = source.read()
                empty_reason, matched = _inspect(path, content, tuple(by_stem.get(path_key(os.path.splitext(path)[0]), ())), by_name)
                after = fingerprint_path(path)
                if before != after:
                    raise CleanupError("changed", path)
            except (OSError, ValueError, ElementTree.ParseError, CleanupError) as error:
                skipped.append((path, error if isinstance(error, (OSError, CleanupError)) else CleanupError("invalid")))
                continue
            if not matched or empty_reason:
                items.append(CleanupItem(path, "orphan" if not matched else empty_reason, after, tuple(matched)))
    return CleanupPlan(image_dir, annotation_dir, extensions, tuple(items), tuple(skipped), images, scopes)


def verify_cleanup_selection(plan, items, report=None):
    """Reclassify against disk so newly added images cannot turn into losses."""
    selected = {path_key(item.path): item for item in items}
    if not selected or any(item not in plan.items for item in items):
        raise CleanupError("selection")
    current = scan_cleanup(plan.image_dir, plan.annotation_dir, plan.extensions, report)
    fresh = {path_key(item.path): item for item in current.items}
    for key, item in selected.items():
        if fresh.get(key) != item:
            raise CleanupError("changed", item.path)
    return tuple(selected.values())
