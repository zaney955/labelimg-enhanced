"""CreateML collection identity, validation, and record transformations."""

from copy import deepcopy
from dataclasses import dataclass, field
import json
import ntpath
import os


class CreateMLCollectionError(ValueError):
    pass


class CreateMLCollectionParseError(CreateMLCollectionError):
    pass


class CreateMLCollectionFormatError(CreateMLCollectionError):
    pass


class CreateMLRecordNotFound(CreateMLCollectionError):
    pass


class CreateMLRecordAmbiguous(CreateMLCollectionError):
    pass


def normalize_image_reference(value):
    """Return a platform-independent key for a CreateML image reference."""
    text = os.fspath(value).replace("/", "\\")
    return ntpath.normpath(text).casefold()


@dataclass(frozen=True)
class CreateMLRecordIdentity:
    collection_path: str
    reference: str

    def __post_init__(self):
        object.__setattr__(
            self,
            "collection_path",
            os.path.abspath(os.fspath(self.collection_path)),
        )
        object.__setattr__(self, "reference", os.fspath(self.reference))

    @property
    def reference_key(self):
        return normalize_image_reference(self.reference)

    @property
    def key(self):
        return (
            os.path.normcase(self.collection_path),
            self.reference_key,
        )

    def matches(self, image_path):
        reference_key = self.reference_key
        image_key = normalize_image_reference(
            os.path.abspath(os.fspath(image_path))
        )
        if ntpath.isabs(reference_key):
            return reference_key == image_key
        if "\\" not in reference_key:
            return ntpath.basename(image_key) == reference_key
        if image_key.endswith("\\" + reference_key):
            return True
        resolved = os.path.abspath(
            os.path.join(
                os.path.dirname(self.collection_path),
                *reference_key.split("\\"),
            )
        )
        return normalize_image_reference(resolved) == image_key


@dataclass(frozen=True)
class CreateMLRecord:
    identity: CreateMLRecordIdentity
    _payload: dict = field(repr=False, compare=False)

    @property
    def reference(self):
        return self.identity.reference

    @property
    def labels(self):
        return tuple(
            annotation["label"].strip()
            for annotation in self._annotations
            if (
                isinstance(annotation, dict)
                and isinstance(annotation.get("label"), str)
                and annotation["label"].strip()
            )
        )

    @property
    def has_annotations(self):
        return bool(self._annotations)

    @property
    def verified(self):
        return bool(
            self._payload.get("verified", bool(self._annotations))
        )

    @property
    def questioned(self):
        return bool(self._payload.get("questioned", False))

    @property
    def reader_shapes(self):
        shapes = []
        for annotation in self._annotations:
            coordinates = annotation["coordinates"]
            x_min = coordinates["x"] - coordinates["width"] / 2
            y_min = coordinates["y"] - coordinates["height"] / 2
            x_max = coordinates["x"] + coordinates["width"] / 2
            y_max = coordinates["y"] + coordinates["height"] / 2
            shapes.append(
                (
                    annotation["label"],
                    (
                        (x_min, y_min),
                        (x_max, y_min),
                        (x_max, y_max),
                        (x_min, y_max),
                    ),
                    None,
                    None,
                    True,
                )
            )
        return tuple(shapes)

    @property
    def _annotations(self):
        annotations = self._payload.get("annotations", ())
        return annotations if isinstance(annotations, list) else ()

    def _with_reference(self, reference):
        payload = deepcopy(self._payload)
        payload["image"] = os.fspath(reference)
        return CreateMLRecord(
            CreateMLRecordIdentity(
                self.identity.collection_path,
                reference,
            ),
            payload,
        )

    def _for_collection(self, collection_path):
        return CreateMLRecord(
            CreateMLRecordIdentity(collection_path, self.reference),
            deepcopy(self._payload),
        )

    def _payload_copy(self):
        return deepcopy(self._payload)


@dataclass(frozen=True)
class CreateMLRenamePlan:
    changed: bool
    source: "CreateMLAnnotationCollection | None" = None
    targets: tuple = ()


_UNSET = object()


class CreateMLAnnotationCollection:
    """Own complete-reference identity and collection transformations."""

    def __init__(self, path, records=()):
        self.path = os.path.abspath(os.fspath(path))
        self._records = tuple(
            record._for_collection(self.path) for record in records
        )

    @classmethod
    def empty(cls, path):
        return cls(path)

    @classmethod
    def read(
        cls,
        path,
        *,
        content=_UNSET,
        missing_ok=False,
        strict=False,
    ):
        path = os.path.abspath(os.fspath(path))
        if content is _UNSET:
            try:
                with open(path, "rb") as source:
                    content = source.read()
            except FileNotFoundError:
                if missing_ok:
                    return cls.empty(path)
                raise
            except OSError as error:
                raise CreateMLCollectionParseError(
                    "Could not read CreateML JSON %s: %s" % (path, error)
                ) from error
        try:
            if isinstance(content, bytes):
                content = content.decode("utf8")
            payload = json.loads(content)
        except (UnicodeError, ValueError, TypeError) as error:
            raise CreateMLCollectionParseError(
                "Could not parse CreateML JSON %s: %s" % (path, error)
            ) from error
        if not isinstance(payload, list):
            raise CreateMLCollectionFormatError(
                "CreateML JSON root must be a list"
            )
        records = []
        for item in payload:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("image"), str)
            ):
                raise CreateMLCollectionFormatError(
                    "CreateML record must contain an image reference"
                )
            if strict:
                _validate_record(item)
            records.append(
                CreateMLRecord(
                    CreateMLRecordIdentity(path, item["image"]),
                    deepcopy(item),
                )
            )
        return cls(path, records)

    @property
    def records(self):
        return self._records

    @property
    def references(self):
        return tuple(record.reference for record in self._records)

    @property
    def normalized_references(self):
        return tuple(
            record.identity.reference_key for record in self._records
        )

    @property
    def labels(self):
        return tuple(
            label for record in self._records for label in record.labels
        )

    @property
    def has_annotations(self):
        return any(record._annotations for record in self._records)

    @property
    def verified(self):
        return any(record.verified for record in self._records)

    @property
    def questioned(self):
        return any(record.questioned for record in self._records)

    def __len__(self):
        return len(self._records)

    def resolve(self, image_path, *, required=True):
        matches = tuple(
            record
            for record in self._records
            if record.identity.matches(image_path)
        )
        if len(matches) > 1:
            raise CreateMLRecordAmbiguous(
                "CreateML collection contains multiple matching records "
                "for %s" % image_path
            )
        if not matches:
            if not required:
                return None
            raise CreateMLRecordNotFound(
                "CreateML collection has no matching record for %s"
                % image_path
            )
        return matches[0]

    def contains_image(self, image_path):
        return any(
            record.identity.matches(image_path)
            for record in self._records
        )

    def upsert_annotation_record(
        self,
        reference,
        shapes,
        *,
        verified=False,
        questioned=False,
    ):
        reference = os.fspath(reference)
        payload = {
            "image": reference,
            "annotations": tuple(
                _annotation_from_shape(shape) for shape in shapes
            ),
            "verified": bool(verified),
            "questioned": bool(questioned),
        }
        payload["annotations"] = list(payload["annotations"])
        replacement = CreateMLRecord(
            CreateMLRecordIdentity(self.path, reference), payload
        )
        reference_key = normalize_image_reference(reference)
        records = []
        replaced = False
        for record in self._records:
            if record.identity.reference_key == reference_key:
                records.append(replacement)
                replaced = True
            else:
                records.append(record)
        if not replaced:
            records.append(replacement)
        return CreateMLAnnotationCollection(self.path, records)

    def remove_image(self, image_path, *, required=False):
        record = self.resolve(image_path, required=required)
        if record is None:
            return self
        return CreateMLAnnotationCollection(
            self.path,
            tuple(
                candidate
                for candidate in self._records
                if candidate is not record
            ),
        )

    def merge(self, other):
        records = list(self._records)
        keys = {
            record.identity.reference_key for record in self._records
        }
        for record in other.records:
            key = record.identity.reference_key
            if key in keys:
                raise CreateMLCollectionFormatError(
                    "CreateML target already contains image %s: %s"
                    % (record.reference, self.path)
                )
            keys.add(key)
            records.append(record)
        return CreateMLAnnotationCollection(self.path, records)

    def plan_rename(self, mapping, *, exact_owner=None):
        mapping = {
            os.path.abspath(os.fspath(source)): os.path.abspath(
                os.fspath(target)
            )
            for source, target in mapping.items()
        }
        matched = []
        retained = []
        counts = {}
        for record in self._records:
            owners = tuple(
                source
                for source in mapping
                if record.identity.matches(source)
            )
            if len(owners) > 1:
                raise CreateMLRecordAmbiguous(
                    "CreateML record is ambiguous for %s"
                    % record.reference
                )
            if not owners:
                retained.append(record)
                continue
            owner = owners[0]
            counts[owner] = counts.get(owner, 0) + 1
            changed = record._with_reference(
                _renamed_reference(record.reference, mapping[owner])
            )
            matched.append((owner, changed))
        duplicate_owner = next(
            (owner for owner, count in counts.items() if count > 1),
            None,
        )
        if duplicate_owner is not None:
            raise CreateMLRecordAmbiguous(
                "CreateML collection has multiple records for %s: %s"
                % (os.path.basename(duplicate_owner), self.path)
            )
        if not matched:
            if exact_owner is not None and self._records:
                raise CreateMLRecordNotFound(
                    "Associated CreateML collection has no matching record: "
                    "%s" % self.path
                )
            return CreateMLRenamePlan(False)
        if exact_owner is None:
            replacements = dict(matched)
            rewritten = tuple(
                replacements.get(
                    next(
                        (
                            owner
                            for owner in mapping
                            if record.identity.matches(owner)
                        ),
                        None,
                    ),
                    record,
                )
                for record in self._records
            )
            return CreateMLRenamePlan(
                True,
                source=CreateMLAnnotationCollection(self.path, rewritten),
            )
        targets = tuple(
            (
                _renamed_collection_path(self.path, mapping[owner]),
                CreateMLAnnotationCollection(
                    _renamed_collection_path(self.path, mapping[owner]),
                    (record,),
                ),
            )
            for owner, record in matched
        )
        source = (
            CreateMLAnnotationCollection(self.path, retained)
            if retained
            else None
        )
        return CreateMLRenamePlan(True, source=source, targets=targets)

    def to_bytes(self, *, indent=None, ensure_ascii=True):
        return json.dumps(
            tuple(record._payload_copy() for record in self._records),
            ensure_ascii=ensure_ascii,
            indent=indent,
        ).encode("utf8")

    def write(self, path=None):
        target = self.path if path is None else os.path.abspath(path)
        with open(target, "wb") as output:
            output.write(self.to_bytes())
        return target


def _validate_record(record):
    annotations = record.get("annotations")
    if not isinstance(annotations, list):
        raise CreateMLCollectionFormatError(
            "CreateML record must contain annotations"
        )
    for annotation in annotations:
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
            raise CreateMLCollectionFormatError(
                "CreateML annotation is structurally invalid"
            )


def _annotation_from_shape(shape):
    points = shape["points"]
    x_values = (points[0][0], points[1][0])
    y_values = (points[0][1], points[2][1])
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    width = x_max - x_min
    height = y_max - y_min
    return {
        "label": shape["label"],
        "coordinates": {
            "x": x_min + width / 2,
            "y": y_min + height / 2,
            "width": width,
            "height": height,
        },
    }


def _renamed_reference(reference, target):
    reference = os.fspath(reference)
    normalized = reference.replace("\\", "/")
    if os.path.isabs(reference):
        return os.path.abspath(target)
    if "/" not in normalized:
        return os.path.basename(target)
    prefix = normalized.rpartition("/")[0]
    renamed = prefix + "/" + os.path.basename(target)
    return renamed.replace("/", "\\") if "\\" in reference else renamed


def _renamed_collection_path(collection_path, target_image):
    stem = os.path.splitext(os.path.basename(target_image))[0]
    return os.path.join(os.path.dirname(collection_path), stem + ".json")
