"""Physical annotation resource identity and save coordination."""

from dataclasses import dataclass, replace
import hashlib
import os
import shutil
import tempfile
import threading
import uuid


@dataclass(frozen=True)
class ResourceFingerprint:
    exists: bool
    size: int = 0
    modified_ns: int = 0
    sha256: str = ""


MISSING_FINGERPRINT = ResourceFingerprint(False)


@dataclass(frozen=True)
class AnnotationResource:
    path: str
    expected_fingerprint: ResourceFingerprint | None = None


@dataclass(frozen=True)
class AnnotationSaveRequest:
    image_key: str
    revision_id: int
    target: str
    resources: tuple
    payload: object = None
    precommit: object = None

    def __post_init__(self):
        if not all(
            isinstance(resource, AnnotationResource)
            for resource in self.resources
        ):
            raise TypeError(
                "resources must contain AnnotationResource values"
            )


@dataclass(frozen=True)
class AnnotationSaveResult:
    image_key: str
    revision_id: int
    target: str
    fingerprints: tuple
    writer_result: object = None


class AnnotationStorageError(RuntimeError):
    pass


class AnnotationStorageConflict(AnnotationStorageError):
    def __init__(self, mismatches):
        self.mismatches = tuple(mismatches)
        super().__init__(
            "annotation resources changed outside LabelImg: %s"
            % ", ".join(path for path, _expected, _actual in mismatches)
        )


class AnnotationStorageCoordinator:
    """Serialize writes by every physical resource they touch."""

    def __init__(self):
        self._lock_guard = threading.Lock()
        self._resource_locks = {}

    def save(self, request, writer):
        return self.save_batch(
            (request,),
            lambda requests: writer(requests[0]),
        )[0]

    def save_batch(self, requests, writer):
        requests = tuple(requests)
        if not requests:
            return ()
        resources = tuple(
            sorted(
                {
                    _resource_key(resource.path)
                    for request in requests
                    for resource in request.resources
                }
            )
        )
        locks = self._locks_for(resources)
        for lock in locks:
            lock.acquire()
        try:
            self._verify_expected(requests)
            guarded_requests = tuple(
                replace(
                    request,
                    precommit=lambda: self._verify_expected(requests),
                )
                for request in requests
            )
            writer_result = writer(guarded_requests)
            results = []
            for request in requests:
                fingerprints = tuple(
                    (resource.path, fingerprint_path(resource.path))
                    for resource in request.resources
                )
                results.append(
                    AnnotationSaveResult(
                        image_key=request.image_key,
                        revision_id=request.revision_id,
                        target=request.target,
                        fingerprints=fingerprints,
                        writer_result=writer_result,
                    )
                )
            return tuple(results)
        finally:
            for lock in reversed(locks):
                lock.release()

    @staticmethod
    def _verify_expected(requests):
        expected_by_key = {}
        path_by_key = {}
        for request in requests:
            for resource in request.resources:
                key = _resource_key(resource.path)
                expected = resource.expected_fingerprint
                if (
                    key in expected_by_key
                    and expected_by_key[key] != expected
                ):
                    raise AnnotationStorageError(
                        "batch has inconsistent expected fingerprints for %s"
                        % resource.path
                    )
                expected_by_key[key] = expected
                path_by_key[key] = resource.path
        mismatches = []
        for key, expected in expected_by_key.items():
            if expected is None:
                continue
            path = path_by_key[key]
            actual = fingerprint_path(path)
            if actual != expected:
                mismatches.append((path, expected, actual))
        if mismatches:
            raise AnnotationStorageConflict(mismatches)

    def lease(self, resources):
        return _ResourceLease(
            self._locks_for(
                tuple(
                    sorted(
                        {_resource_key(path) for path in resources}
                    )
                )
            )
        )

    def _locks_for(self, resources):
        with self._lock_guard:
            return tuple(
                self._resource_locks.setdefault(
                    resource,
                    threading.RLock(),
                )
                for resource in resources
            )


class _ResourceLease:
    def __init__(self, locks):
        self._locks = locks

    def __enter__(self):
        for lock in self._locks:
            lock.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        for lock in reversed(self._locks):
            lock.release()
        return False


def fingerprint_path(path):
    """Return a content-sensitive identity, including explicit absence."""
    path = os.path.abspath(os.fspath(path))
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return MISSING_FINGERPRINT
    digest = hashlib.sha256()
    with open(path, "rb") as resource:
        for chunk in iter(lambda: resource.read(1024 * 1024), b""):
            digest.update(chunk)
    return ResourceFingerprint(
        exists=True,
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        sha256=digest.hexdigest(),
    )


def _resource_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


class AtomicAnnotationWriter:
    """Stage complete format outputs and commit peer resources atomically."""

    def write(
        self,
        document,
        annotation_format,
        target,
        base_resources=None,
        precommit=None,
    ):
        from dataclasses import replace

        from labelimg.annotation_document import AnnotationFormat

        target = _target_with_extension(target, annotation_format.extension)
        base_resources = base_resources or {}
        os.makedirs(os.path.dirname(target) or os.curdir, exist_ok=True)
        if (
            annotation_format is AnnotationFormat.PASCAL_VOC
            and not document.boxes
            and not document.verified
            and not document.questioned
        ):
            removed = os.path.isfile(target)
            if removed:
                if precommit is not None:
                    precommit()
                _atomic_remove(target)
            return target, removed

        if annotation_format is AnnotationFormat.YOLO:
            staging_dir = tempfile.mkdtemp(
                prefix=".labelimg-yolo-",
                dir=os.path.dirname(target) or os.curdir,
            )
            try:
                staged_target = os.path.join(
                    staging_dir,
                    os.path.basename(target),
                )
                classes_target = os.path.join(
                    os.path.dirname(target),
                    "classes.txt",
                )
                if classes_target in base_resources:
                    existing_classes = [
                        line.strip()
                        for line in base_resources[
                            classes_target
                        ].decode("utf8").splitlines()
                        if line.strip()
                    ]
                else:
                    existing_classes = _read_classes(classes_target)
                stable_classes = _stable_labels(
                    existing_classes
                    + list(document.class_names)
                    + [box.label for box in document.boxes]
                )
                staged_document = replace(
                    document,
                    class_names=tuple(stable_classes),
                )
                staged_document.save(
                    staged_target,
                    annotation_format,
                )
                staged_classes = os.path.join(
                    staging_dir,
                    "classes.txt",
                )
                if precommit is not None:
                    precommit()
                _atomic_commit_staged(
                    (
                        (staged_target, target),
                        (staged_classes, classes_target),
                    )
                )
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)
            return target, False

        staged = _peer_temp_path(target)
        try:
            if (
                annotation_format is AnnotationFormat.CREATE_ML
            ):
                if target in base_resources:
                    with open(staged, "wb") as staged_file:
                        staged_file.write(base_resources[target])
                elif os.path.isfile(target):
                    shutil.copy2(target, staged)
            document.save(staged, annotation_format)
            if precommit is not None:
                precommit()
            _atomic_commit_staged(((staged, target),))
        finally:
            if os.path.exists(staged):
                os.remove(staged)
        return target, False

    def write_createml_collection(
        self,
        documents,
        target,
        base_resources=None,
        precommit=None,
    ):
        from labelimg.annotation_document import AnnotationFormat

        target = _target_with_extension(
            target, AnnotationFormat.CREATE_ML.extension
        )
        base_resources = base_resources or {}
        os.makedirs(os.path.dirname(target) or os.curdir, exist_ok=True)
        staged = _peer_temp_path(target)
        try:
            if target in base_resources:
                with open(staged, "wb") as staged_file:
                    staged_file.write(base_resources[target])
            elif os.path.isfile(target):
                shutil.copy2(target, staged)
            for document in documents:
                document.save(staged, AnnotationFormat.CREATE_ML)
            if precommit is not None:
                precommit()
            _atomic_commit_staged(((staged, target),))
        finally:
            if os.path.exists(staged):
                os.remove(staged)
        return target, False


def _target_with_extension(path, extension):
    path = os.path.abspath(os.fspath(path))
    return path if path.lower().endswith(extension) else path + extension


def _peer_temp_path(target):
    directory = os.path.dirname(target) or os.curdir
    stem, extension = os.path.splitext(os.path.basename(target))
    return os.path.join(
        directory,
        ".%s.%s.tmp%s" % (stem, uuid.uuid4().hex, extension),
    )


def _atomic_remove(target):
    backup = _peer_temp_path(target) + ".remove"
    os.replace(target, backup)
    try:
        os.remove(backup)
    except Exception:
        if not os.path.exists(target) and os.path.exists(backup):
            os.replace(backup, target)
        raise


def _atomic_commit_staged(staged_pairs, replace=os.replace):
    staged_pairs = tuple(
        (os.path.abspath(staged), os.path.abspath(target))
        for staged, target in staged_pairs
    )
    backups = {}
    committed = []
    try:
        for _staged, target in staged_pairs:
            if os.path.exists(target):
                backup = _peer_temp_path(target) + ".backup"
                replace(target, backup)
                backups[target] = backup
        for staged, target in staged_pairs:
            replace(staged, target)
            committed.append(target)
    except Exception:
        rollback_errors = []
        for target in reversed(committed):
            try:
                if os.path.exists(target):
                    os.remove(target)
            except Exception as error:
                rollback_errors.append(error)
        for target, backup in reversed(tuple(backups.items())):
            try:
                if os.path.exists(backup):
                    replace(backup, target)
            except Exception as error:
                rollback_errors.append(error)
        if rollback_errors:
            raise AnnotationStorageError(
                "atomic annotation rollback failed: %s"
                % rollback_errors[0]
            )
        raise
    else:
        for backup in backups.values():
            try:
                if os.path.exists(backup):
                    os.remove(backup)
            except OSError:
                # The new resources are already committed. A locked backup
                # must not make callers retain a stale saved baseline.
                pass


def _read_classes(path):
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf8") as class_file:
        return [line.strip() for line in class_file if line.strip()]


def _stable_labels(labels):
    result = []
    seen = set()
    for label in labels:
        if label and label not in seen:
            seen.add(label)
            result.append(label)
    return result
