import os
import tempfile
import unittest
from types import SimpleNamespace

from PIL import Image

from labelimg.annotations.domain.model import AnnotationDocument
from labelimg.annotations.domain.history import AnnotationSnapshot
from labelimg.annotations.infrastructure.storage import fingerprint_image, fingerprint_path
from labelimg.image_tools.infrastructure.recoverable_replacement import (
    PreparedImageReplacement,
)
from labelimg.image_tools.application.session import (
    GeometryTransformChange,
    ImageProcessingProjectionKind,
    ImageProcessingProjectionError,
    ImageProcessingSession,
    PreparedPixelChange,
)


class _Editing:
    def __init__(self, view=None, events=None):
        self.view = view
        self._events = events if events is not None else []

    def rebase_image(self, path, snapshot, baseline=None):
        self._events.append(("rebase", path, snapshot, baseline))

    def select_image(self, path):
        self._events.append(("select", path))


class _Persistence:
    def __init__(self, events):
        self._events = events

    def propagate_resource_fingerprints(self, fingerprints):
        self._events.append(("fingerprints", tuple(fingerprints)))


class _Workspace:
    yolo_vocabulary = ()

    @staticmethod
    def active_document_path(_path):
        return None


class _Operations:
    def __init__(self, events):
        self._events = events
        self.recovery_entries = ()

    def execute_image_processing(self, replacements, *, target_count=None):
        replacements = tuple(replacements)
        self._events.append(("commit-pixel", replacements, target_count))
        return SimpleNamespace(
            file_result=SimpleNamespace(
                resources=tuple(
                    SimpleNamespace(original_path=item.path)
                    for item in replacements
                )
            ),
            recovery_entry=object(),
        )

    def execute_grouped_image_processing(
        self,
        image_path,
        replacements,
        *,
        mergeable_create_ml_paths=(),
    ):
        self._events.append((
            "commit-current-geometry",
            image_path,
            tuple(replacements),
            tuple(mergeable_create_ml_paths),
        ))
        return SimpleNamespace(recovery_entry=object())

    def execute_grouped_image_processing_batch(self, groups):
        self._events.append(("commit-geometry-batch", tuple(groups)))
        return SimpleNamespace(recovery_entry=object())

    def discard_image_histories(self, paths):
        self._events.append(("discard-histories", tuple(paths)))

    def recover(self, entry_id, selected_paths=None):
        self._events.append(("recover", entry_id, tuple(selected_paths or ())))
        return SimpleNamespace(
            restored_paths=("restored.png",),
            reload_images=(),
        )


class ImageProcessingSessionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.events = []
        self.operations = _Operations(self.events)
        self.editing = _Editing(events=self.events)
        self.persistence = _Persistence(self.events)
        self.projections = []
        self.projection_error_kind = None
        self.session = ImageProcessingSession(
            workspace=_Workspace(),
            editing=self.editing,
            persistence=self.persistence,
            operations=self.operations,
            project=self._project,
            document_for_path=self._document_for_path,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _project(self, request):
        self.events.append(("project", request.kind, request.paths))
        self.projections.append(request)
        if request.kind is self.projection_error_kind:
            raise RuntimeError("projection exploded")

    @staticmethod
    def _document_for_path(path):
        with open(path, "rb") as source:
            content = source.read()
        return AnnotationDocument(path, content, boxes=(), class_names=())

    def _image(self, name="image.png", content=b"before"):
        path = os.path.join(self.temporary.name, name)
        Image.new("RGB", (20, 10), "white").save(path)
        return path

    def _snapshot(self, path):
        return AnnotationSnapshot(
            image_key=path,
            image_size=(20, 10),
            boxes=(),
            verified=False,
            questioned=False,
            image_fingerprint=fingerprint_image(path, (20, 10)),
        )

    def test_pixel_commit_projects_changed_paths_after_atomic_commit(self):
        path = self._image()
        replacement = PreparedImageReplacement(
            path,
            fingerprint_path(path),
            b"after",
        )

        plan = self.session.prepare(PreparedPixelChange(
            (replacement,),
            target_count=1,
        ))
        outcome = self.session.commit(plan)

        self.assertIsNotNone(outcome.recovery_entry)
        self.assertEqual(
            [event[0] for event in self.events],
            ["commit-pixel", "project"],
        )
        projection = self.projections[-1]
        self.assertIs(
            projection.kind,
            ImageProcessingProjectionKind.PIXEL_COMMIT,
        )
        self.assertEqual(projection.paths, (os.path.abspath(path),))

    def test_current_geometry_projects_then_rebases_one_clean_baseline(self):
        path = self._image()
        self.editing.view = SimpleNamespace(
            snapshot=self._snapshot(path),
            current_target=None,
        )
        plan = self.session.prepare(GeometryTransformChange(
            paths=(path,),
            operation="rotate-180",
            current_path=path,
            preserve_current=True,
        ))

        self.session.commit(plan)

        self.assertEqual(
            [event[0] for event in self.events],
            [
                "commit-current-geometry",
                "project",
                "rebase",
                "select",
            ],
        )
        projection = self.projections[-1]
        self.assertIs(
            projection.kind,
            ImageProcessingProjectionKind.CURRENT_GEOMETRY_COMMIT,
        )
        self.assertEqual(projection.direction, "geometry-transform")
        self.assertEqual(projection.current_target.path, path)
        self.assertEqual(
            projection.snapshot.image_fingerprint,
            fingerprint_image(path, (20, 10)),
        )

    def test_geometry_batch_discards_retained_histories_before_reload(self):
        first = self._image("first.png")
        second = self._image("second.png")
        self.editing.view = SimpleNamespace(
            snapshot=self._snapshot(first),
            current_target=None,
        )
        plan = self.session.prepare(GeometryTransformChange(
            paths=(first, second),
            operation="resize",
            current_path=first,
            resize_percent=50,
        ))

        self.session.commit(plan)

        self.assertEqual(
            [event[0] for event in self.events],
            ["commit-geometry-batch", "discard-histories", "project"],
        )
        projection = self.projections[-1]
        self.assertIs(
            projection.kind,
            ImageProcessingProjectionKind.GEOMETRY_BATCH_COMMIT,
        )
        self.assertEqual(projection.paths, (first, second))

    def test_recovery_uses_the_same_projection_seam(self):
        outcome = self.session.recover("entry-1", selected_paths=("a.png",))

        self.assertEqual(outcome.restored_paths, ("restored.png",))
        self.assertEqual(
            [event[0] for event in self.events],
            ["recover", "project"],
        )
        projection = self.projections[-1]
        self.assertIs(
            projection.kind,
            ImageProcessingProjectionKind.RECOVERY,
        )
        self.assertEqual(
            projection.paths,
            (os.path.abspath("restored.png"),),
        )

    def test_prepared_plan_is_single_use(self):
        path = self._image()
        replacement = PreparedImageReplacement(
            path,
            fingerprint_path(path),
            b"after",
        )
        plan = self.session.prepare(PreparedPixelChange((replacement,)))

        self.session.commit(plan)

        with self.assertRaisesRegex(ValueError, "committed once"):
            self.session.commit(plan)

    def test_projection_failure_is_typed_and_requests_editing_block(self):
        path = self._image()
        self.editing.view = SimpleNamespace(
            snapshot=self._snapshot(path),
            current_target=None,
        )
        plan = self.session.prepare(GeometryTransformChange(
            paths=(path,),
            operation="rotate-180",
            current_path=path,
            preserve_current=True,
        ))
        self.projection_error_kind = (
            ImageProcessingProjectionKind.CURRENT_GEOMETRY_COMMIT
        )

        with self.assertRaisesRegex(
            ImageProcessingProjectionError,
            "one editable image-annotation state",
        ):
            self.session.commit(plan)

        self.assertIs(
            self.projections[-1].kind,
            ImageProcessingProjectionKind.PROJECTION_FAILED,
        )
        self.assertEqual(
            [event[0] for event in self.events],
            ["commit-current-geometry", "project", "project"],
        )


if __name__ == "__main__":
    unittest.main()
