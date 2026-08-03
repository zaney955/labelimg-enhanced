"""Transactional review-state recovery across histories and storage."""

from collections import defaultdict
from dataclasses import dataclass, replace
import os
import tempfile

from labelimg.annotation_document import AnnotationDocument, AnnotationFormat
from labelimg.annotation_workspace import annotation_resources
from labelimg.file_recovery import FileRecoveryConflict, FileRecoveryError


@dataclass(frozen=True)
class PreparedReviewRecovery:
    change: object
    document: object
    annotation_format: AnnotationFormat
    target: str


class ReviewRecoveryCoordinator:
    """Restore review fields as one leased, rollback-capable operation."""

    def __init__(self, workspace, editing):
        self._workspace = workspace
        self._editing = editing

    def recover(self, prepared):
        prepared = tuple(prepared)
        rewritten = self._rewrite_histories(prepared)
        resources = tuple(
            dict.fromkeys(
                resource
                for item in prepared
                for resource in annotation_resources(
                    item.annotation_format, item.target
                )
            )
        )
        completed = []
        try:
            with self._workspace.storage_coordinator.lease(resources):
                prepared = self._validate_locked_state(prepared)
                before = {
                    resource: self._read_resource_bytes(resource)
                    for resource in resources
                }
                completed_resources = set()
                try:
                    self._write(
                        prepared,
                        completed,
                        completed_resources,
                    )
                    for item, saved in completed:
                        if self._editing.has_image(item.change.image_path):
                            self._editing.update_baseline_fingerprint(
                                item.change.image_path,
                                tuple(saved.fingerprints),
                            )
                    self._refresh_dirty_candidates(
                        item.change for item in prepared
                    )
                except Exception as write_error:
                    rollback_errors = []
                    for resource in completed_resources:
                        try:
                            self._restore_resource_bytes(
                                resource, before[resource]
                            )
                        except Exception as rollback_error:
                            rollback_errors.append(
                                "%s: %s" % (resource, rollback_error)
                            )
                    if rollback_errors:
                        raise FileRecoveryError(
                            "Review recovery rollback failed: %s"
                            % "; ".join(rollback_errors)
                        ) from write_error
                    raise
        except Exception as error:
            rollback_errors = self._rollback_histories(rewritten)
            self._refresh_dirty_candidates(
                change for change, _fingerprint in rewritten
            )
            if rollback_errors:
                raise FileRecoveryError(
                    "Review recovery rollback failed: %s"
                    % "; ".join(rollback_errors)
                ) from error
            if isinstance(error, FileRecoveryError):
                raise
            raise FileRecoveryError(str(error)) from error
        return tuple(completed)

    def _rewrite_histories(self, prepared):
        rewritten = []
        try:
            for item in prepared:
                change = item.change
                if not self._editing.has_image(change.image_path):
                    continue
                view = self._editing.view_image(
                    change.image_path, touch=False
                )
                old_fingerprint = (
                    view.saved_baseline.fingerprint
                    if view.saved_baseline is not None
                    else None
                )
                self._editing.rewrite_review_state(
                    change.image_path,
                    (
                        change.result_verified,
                        change.result_questioned,
                    ),
                    (
                        change.prior_verified,
                        change.prior_questioned,
                    ),
                    old_fingerprint,
                )
                rewritten.append((change, old_fingerprint))
        except Exception as error:
            self._rollback_histories(rewritten)
            raise FileRecoveryConflict(str(error)) from error
        return tuple(rewritten)

    def _rollback_histories(self, rewritten):
        errors = []
        for change, old_fingerprint in reversed(rewritten):
            try:
                self._editing.rewrite_review_state(
                    change.image_path,
                    (
                        change.prior_verified,
                        change.prior_questioned,
                    ),
                    (
                        change.result_verified,
                        change.result_questioned,
                    ),
                    old_fingerprint,
                )
            except Exception as error:
                errors.append("%s history: %s" % (change.image_path, error))
        return errors

    def _write(self, prepared, completed, completed_resources):
        create_ml_groups = defaultdict(list)
        ordinary = []
        for item in prepared:
            change = item.change
            item.document.verified = change.prior_verified
            item.document.questioned = change.prior_questioned
            if item.annotation_format is AnnotationFormat.CREATE_ML:
                create_ml_groups[self._resource_key(item.target)].append(item)
            else:
                ordinary.append(item)

        for item in ordinary:
            completed_resources.update(
                annotation_resources(
                    item.annotation_format, item.target
                )
            )
            saved = self._workspace.save(
                item.document,
                item.annotation_format,
                annotation_path=item.target,
            )
            completed.append((item, saved))
            completed_resources.update(
                path for path, _fingerprint in saved.fingerprints
            )
        for target, group in create_ml_groups.items():
            completed_resources.update(
                annotation_resources(
                    AnnotationFormat.CREATE_ML, target
                )
            )
            saves = self._workspace.save_createml_batch(
                tuple((1, item.document) for item in group), target
            )
            completed.extend(zip(group, saves))
            for saved in saves:
                completed_resources.update(
                    path for path, _fingerprint in saved.fingerprints
                )

    @staticmethod
    def _validate_locked_state(prepared):
        validated = []
        for item in prepared:
            change = item.change
            if (
                not os.path.exists(item.target)
                and item.annotation_format
                is AnnotationFormat.PASCAL_VOC
                and not change.result_verified
                and not change.result_questioned
            ):
                current = replace(
                    item.document,
                    boxes=(),
                    verified=False,
                    questioned=False,
                )
            else:
                current = AnnotationDocument.load(
                    item.target,
                    change.image_path,
                    item.document.image_data,
                )
            if (
                current.verified != change.result_verified
                or current.questioned != change.result_questioned
            ):
                raise FileRecoveryConflict(
                    "Review state changed again for %s"
                    % change.image_path
                )
            validated.append(replace(item, document=current))
        return tuple(validated)

    def _refresh_dirty_candidates(self, changes):
        for change in changes:
            if not self._editing.has_image(change.image_path):
                continue
            view = self._editing.view_image(
                change.image_path, touch=False
            )
            if not view.dirty or not view.current_target:
                continue
            self._workspace.record_document(
                change.image_path,
                view.current_target,
                (box.label for box in view.snapshot.boxes),
            )

    @staticmethod
    def _resource_key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _read_resource_bytes(path):
        try:
            with open(path, "rb") as source:
                return source.read()
        except FileNotFoundError:
            return None

    @staticmethod
    def _restore_resource_bytes(path, content):
        if content is None:
            if os.path.exists(path):
                os.remove(path)
            return
        directory = os.path.dirname(path) or os.curdir
        descriptor, staged = tempfile.mkstemp(
            prefix=".labelimg-review-rollback-", dir=directory
        )
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
            os.replace(staged, path)
        finally:
            if os.path.exists(staged):
                os.remove(staged)
