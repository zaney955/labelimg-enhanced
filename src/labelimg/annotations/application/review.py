"""Review-state transactions across documents, histories, and storage."""

from collections import defaultdict
from dataclasses import dataclass, replace
import os
import tempfile

from labelimg.annotations.domain.model import (
    AnnotationBox,
    AnnotationFormat,
)
from labelimg.annotations.infrastructure.document import AnnotationDocument
from labelimg.annotations.application.workspace import annotation_resources
from labelimg.platform.recovery import (
    RecoveryConflict as FileRecoveryConflict,
    RecoveryError as FileRecoveryError,
)


@dataclass(frozen=True)
class ReviewRecoveryRecord:
    image_path: str
    prior_verified: bool
    prior_questioned: bool
    result_verified: bool
    result_questioned: bool
    annotation_path: str | None = None


@dataclass(frozen=True)
class ReviewUpdate:
    """One successfully persisted review-state update."""

    image_path: str
    document: object
    snapshot: object = None
    recovery_record: object = None


@dataclass(frozen=True)
class ReviewTransactionResult:
    """Observable outcome of applying or recovering review state."""

    updates: tuple = ()
    failures: tuple = ()

    @property
    def recovery_records(self):
        return tuple(
            update.recovery_record
            for update in self.updates
            if update.recovery_record is not None
        )


@dataclass(frozen=True)
class _PreparedReviewUpdate:
    image_path: str
    view: object
    document: AnnotationDocument
    annotation_format: AnnotationFormat
    target: str
    prior: tuple


@dataclass(frozen=True)
class _PreparedReviewRecovery:
    change: ReviewRecoveryRecord
    document: AnnotationDocument
    annotation_format: AnnotationFormat
    target: str


class ReviewStateTransaction:
    """Apply and recover review state through one transaction interface.

    Forward batches preserve the existing partial-success contract: ordinary
    documents are independent while records sharing one CreateML collection
    succeed or fail together. Recovery is an all-or-nothing leased operation
    with storage and history rollback.
    """

    def __init__(
        self,
        workspace,
        editing,
        persistence,
        *,
        image_data_for,
    ):
        self._workspace = workspace
        self._editing = editing
        self._persistence = persistence
        self._image_data_for = image_data_for

    def apply(self, image_paths, state, default_format):
        """Persist an explicit review state for the supplied images."""
        verified, questioned = self._state_fields(state)
        prepared = []
        failures = []
        for image_path in image_paths:
            try:
                prepared.append(
                    self._prepare_update(
                        str(image_path),
                        verified,
                        questioned,
                        default_format,
                    )
                )
            except Exception as error:
                failures.append((str(image_path), error))

        completed, write_failures = self._write_partial(prepared)
        failures.extend(write_failures)
        updates = tuple(
            self._acknowledge_update(item, saved)
            for item, saved in completed
        )
        return ReviewTransactionResult(updates, tuple(failures))

    def recover(self, changes):
        """Restore a recorded batch as one rollback-capable operation."""
        prepared = tuple(
            self._prepare_recovery(change) for change in tuple(changes)
        )
        completed = self._recover_all(prepared)
        updates = []
        for item, saved in completed:
            self._persistence.propagate_resource_fingerprints(
                saved.fingerprints
            )
            snapshot = None
            if self._editing.has_image(item.change.image_path):
                snapshot = self._editing.view_image(
                    item.change.image_path, touch=False
                ).snapshot
            updates.append(
                ReviewUpdate(
                    image_path=item.change.image_path,
                    document=saved.document,
                    snapshot=snapshot,
                )
            )
        return ReviewTransactionResult(tuple(updates))

    def replace_workspace(self, workspace):
        """Continue transactions against a newly selected workspace."""
        self._workspace = workspace

    @staticmethod
    def _state_fields(state):
        try:
            return {
                "verified": (True, False),
                "questioned": (False, True),
                "unreviewed": (False, False),
            }[state]
        except KeyError as error:
            raise ValueError("unknown review state: %s" % state) from error

    def _prepare_update(
        self,
        image_path,
        verified,
        questioned,
        default_format,
    ):
        view = None
        if self._editing.has_image(image_path):
            view = self._editing.view_image(image_path, touch=False)
            self._persistence.verify_snapshot(view.snapshot)
            self._persistence.verify_baseline(view)
            document = self._document_from_snapshot(view.snapshot)
            target = view.current_target
        else:
            image_data = self._image_data_for(image_path)
            loaded = self._workspace.load_for_image(image_path, image_data)
            document = (
                loaded.document
                if loaded is not None
                else AnnotationDocument(
                    image_path=image_path,
                    image_data=image_data,
                    boxes=(),
                    class_names=(),
                )
            )
            target = loaded.annotation_path if loaded is not None else None
        if target is None:
            target = self._workspace.entry(image_path).path_for(
                default_format
            )
        annotation_format = AnnotationFormat.from_path(target)
        prior = (document.verified, document.questioned)
        document = replace(
            document,
            verified=verified,
            questioned=questioned,
        )
        return _PreparedReviewUpdate(
            image_path,
            view,
            document,
            annotation_format,
            target,
            prior,
        )

    def _document_from_snapshot(self, snapshot):
        return AnnotationDocument(
            image_path=snapshot.image_key,
            image_data=self._image_data_for(snapshot.image_key),
            boxes=tuple(
                AnnotationBox(
                    label=box.label,
                    points=box.points,
                    line_color=box.line_rgba,
                    fill_color=box.fill_rgba,
                    difficult=box.difficult,
                )
                for box in snapshot.boxes
            ),
            class_names=self._workspace.yolo_vocabulary,
            verified=snapshot.verified,
            questioned=snapshot.questioned,
        )

    def _write_partial(self, prepared):
        ordinary, create_ml_groups = self._group_by_resource(prepared)
        completed = []
        failures = []
        for item in ordinary:
            try:
                saved = self._workspace.save(
                    item.document,
                    item.annotation_format,
                    annotation_path=item.target,
                )
                completed.append((item, saved))
            except Exception as error:
                failures.append((item.image_path, error))
        for target, group in create_ml_groups.items():
            try:
                saves = self._workspace.save_createml_batch(
                    tuple(
                        (index + 1, item.document)
                        for index, item in enumerate(group)
                    ),
                    target,
                )
                completed.extend(zip(group, saves))
            except Exception as error:
                failures.extend((item.image_path, error) for item in group)
        return tuple(completed), tuple(failures)

    def _acknowledge_update(self, item, saved):
        self._persistence.propagate_resource_fingerprints(
            saved.fingerprints
        )
        snapshot = None
        if item.view is not None:
            snapshot = replace(
                item.view.snapshot,
                verified=item.document.verified,
                questioned=item.document.questioned,
            )
            snapshot = self._editing.rebase_image(
                item.image_path,
                snapshot,
                baseline=(
                    saved.annotation_path,
                    tuple(saved.fingerprints),
                ),
            ).snapshot
        return ReviewUpdate(
            image_path=item.image_path,
            document=saved.document,
            snapshot=snapshot,
            recovery_record=ReviewRecoveryRecord(
                image_path=item.image_path,
                prior_verified=item.prior[0],
                prior_questioned=item.prior[1],
                result_verified=item.document.verified,
                result_questioned=item.document.questioned,
                annotation_path=saved.annotation_path,
            ),
        )

    def _prepare_recovery(self, change):
        target = change.annotation_path
        if self._editing.has_image(change.image_path):
            target = target or self._editing.view_image(
                change.image_path, touch=False
            ).current_target
        if target is None:
            target = self._workspace.active_document_path(
                change.image_path
            )
        if target is None:
            choices = self._workspace.document_choices(change.image_path)
            if len(choices) != 1:
                raise FileRecoveryConflict(
                    "Review resource is ambiguous for %s"
                    % change.image_path
                )
            target = choices[0].annotation_path
        annotation_format = AnnotationFormat.from_path(target)
        image_data = self._image_data_for(change.image_path)
        if (
            not os.path.exists(target)
            and annotation_format is AnnotationFormat.PASCAL_VOC
            and not change.result_verified
            and not change.result_questioned
        ):
            document = AnnotationDocument(
                image_path=change.image_path,
                image_data=image_data,
            )
        else:
            document = self._workspace.load(
                target, change.image_path, image_data
            ).document
        if (
            document.verified != change.result_verified
            or document.questioned != change.result_questioned
        ):
            raise FileRecoveryConflict(
                "Review state changed again for %s" % change.image_path
            )
        return _PreparedReviewRecovery(
            change,
            document,
            annotation_format,
            target,
        )

    def _recover_all(self, prepared):
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
                    self._write_recovery(
                        prepared,
                        completed,
                        completed_resources,
                    )
                    for item, saved in completed:
                        if self._editing.has_image(
                            item.change.image_path
                        ):
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

    def _write_recovery(
        self,
        prepared,
        completed,
        completed_resources,
    ):
        restored = tuple(
            replace(
                item,
                document=replace(
                    item.document,
                    verified=item.change.prior_verified,
                    questioned=item.change.prior_questioned,
                ),
            )
            for item in prepared
        )
        ordinary, create_ml_groups = self._group_by_resource(restored)
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
    def _group_by_resource(prepared):
        ordinary = []
        create_ml_groups = defaultdict(list)
        for item in prepared:
            if item.annotation_format is AnnotationFormat.CREATE_ML:
                create_ml_groups[
                    ReviewStateTransaction._resource_key(item.target)
                ].append(item)
            else:
                ordinary.append(item)
        return tuple(ordinary), create_ml_groups

    @staticmethod
    def _validate_locked_state(prepared):
        validated = []
        for item in prepared:
            change = item.change
            if (
                not os.path.exists(item.target)
                and item.annotation_format is AnnotationFormat.PASCAL_VOC
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
