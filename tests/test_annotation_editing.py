import unittest
import os
import tempfile
from unittest import mock

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QFocusEvent, QKeyEvent, QMouseEvent, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget

from labelimg.annotation_editing import (
    AnnotationEditingController,
    CanvasAnnotationScene,
    ProjectionRequest,
    ProjectionFailed,
)
from labelimg.annotation_history import (
    AnnotationBoxState,
    AnnotationSnapshot,
    SavedBaseline,
)
from labelimg.annotation_storage import fingerprint_path
from labelimg.canvas import Canvas
from labelimg.app import MainWindow
from labelimg.shape import Shape


def snapshot(label):
    return AnnotationSnapshot(
        image_key="image-a",
        image_size=(100, 100),
        boxes=(
            AnnotationBoxState(
                session_id=1,
                label=label,
                points=((10.0, 10.0), (20.0, 20.0)),
            ),
        ),
    )


class AnnotationEditingControllerTest(unittest.TestCase):
    def test_baseline_mismatch_identifies_changed_yolo_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            labels = os.path.join(directory, "image.txt")
            classes = os.path.join(directory, "classes.txt")
            for path, content in (
                (labels, "0 0.5 0.5 1 1"),
                (classes, "cat"),
            ):
                with open(path, "w", encoding="utf8") as output:
                    output.write(content)
            baseline = SavedBaseline(
                1,
                labels,
                (
                    (labels, fingerprint_path(labels)),
                    (classes, fingerprint_path(classes)),
                ),
            )
            with open(classes, "w", encoding="utf8") as output:
                output.write("dog")

            mismatches = MainWindow._baseline_mismatches(baseline)

        self.assertEqual(
            [os.path.normcase(path) for path, _old, _new in mismatches],
            [os.path.normcase(classes)],
        )

    def test_edit_and_undo_project_one_atomic_result(self):
        scene = {"snapshot": snapshot("cat")}
        projections = []

        def capture(image_key):
            self.assertEqual(image_key, "image-a")
            return scene["snapshot"]

        def project(request):
            self.assertIsInstance(request, ProjectionRequest)
            projections.append(request)
            scene["snapshot"] = request.snapshot

        controller = AnnotationEditingController(capture, project)
        controller.open_image(
            "image-a",
            scene["snapshot"],
            saved_baseline=("a.xml", "v1"),
        )
        controller.begin_edit("Change label")
        scene["snapshot"] = snapshot("dog")
        controller.commit_edit(affected_ids=(1,))

        result = controller.undo()

        self.assertTrue(result.applied)
        self.assertEqual(scene["snapshot"], snapshot("cat"))
        self.assertEqual(projections[-1].affected_ids, (1,))
        self.assertEqual(projections[-1].direction, "undo")
        self.assertTrue(controller.view.can_redo)

    def test_failed_projection_rolls_back_without_moving_cursor(self):
        scene = {"snapshot": snapshot("cat")}
        calls = []

        def project(request):
            calls.append(request.direction)
            if request.direction == "undo":
                raise RuntimeError("target failed")
            scene["snapshot"] = request.snapshot

        controller = AnnotationEditingController(
            lambda _key: scene["snapshot"],
            project,
        )
        controller.open_image("image-a", scene["snapshot"], None)
        controller.begin_edit("Change label")
        scene["snapshot"] = snapshot("dog")
        controller.commit_edit((1,))

        with self.assertRaises(ProjectionFailed):
            controller.undo()

        self.assertEqual(calls, ["undo", "rollback"])
        self.assertEqual(scene["snapshot"], snapshot("dog"))
        self.assertTrue(controller.view.can_undo)
        self.assertFalse(controller.view.can_redo)

    def test_undo_cancels_pending_gesture_without_consuming_history(self):
        scene = {"snapshot": snapshot("cat")}
        canceled = []
        controller = AnnotationEditingController(
            lambda _key: scene["snapshot"],
            lambda request: scene.update(snapshot=request.snapshot),
        )
        controller.open_image("image-a", scene["snapshot"], None)
        controller.begin_edit("Change label")
        scene["snapshot"] = snapshot("dog")
        controller.commit_edit((1,))
        controller.set_pending("Move box", lambda: canceled.append(True))

        result = controller.undo()

        self.assertTrue(result.canceled_pending)
        self.assertEqual(canceled, [True])
        self.assertEqual(controller.view.snapshot, snapshot("dog"))
        self.assertTrue(controller.view.can_undo)

    def test_record_failure_restores_canvas_and_preserves_prior_branch(self):
        scene = {"snapshot": snapshot("cat")}
        controller = AnnotationEditingController(
            lambda _key: scene["snapshot"],
            lambda request: scene.update(snapshot=request.snapshot),
        )
        controller.open_image("image-a", scene["snapshot"], None)
        controller.begin_edit("Change label")
        scene["snapshot"] = snapshot("dog")

        with mock.patch(
            "labelimg.annotation_history._estimate_transition_bytes",
            side_effect=MemoryError("allocation failed"),
        ):
            with self.assertRaises(MemoryError):
                controller.commit_edit((1,))

        self.assertEqual(scene["snapshot"], snapshot("cat"))
        self.assertFalse(controller.edit_open)
        self.assertFalse(controller.view.can_undo)

    def test_migrating_active_image_updates_controller_identity(self):
        scene = {"snapshot": snapshot("cat")}
        controller = AnnotationEditingController(
            lambda _key: scene["snapshot"],
            lambda request: scene.update(snapshot=request.snapshot),
        )
        controller.open_image("image-a", scene["snapshot"], None)
        controller.begin_edit("Change label")
        scene["snapshot"] = snapshot("dog")
        controller.commit_edit((1,))

        controller.migrate_images({"image-a": "renamed-image"})

        self.assertEqual(controller.image_key, "renamed-image")
        self.assertEqual(controller.view.image_key, "renamed-image")
        result = controller.undo()
        self.assertTrue(result.applied)

    def test_dirty_views_include_inactive_images(self):
        scene = {"snapshot": snapshot("cat")}
        controller = AnnotationEditingController(
            lambda _key: scene["snapshot"],
            lambda request: scene.update(snapshot=request.snapshot),
        )
        controller.open_image(
            "image-a", scene["snapshot"], ("a.xml", "saved")
        )
        controller.begin_edit("Change label")
        scene["snapshot"] = snapshot("dog")
        controller.commit_edit((1,))
        second = AnnotationSnapshot(
            image_key="image-b",
            image_size=(100, 100),
        )
        controller.open_image(
            "image-b", second, ("b.xml", "saved")
        )

        self.assertEqual(
            [view.image_key for view in controller.dirty_views()],
            ["image-a"],
        )


class CanvasAnnotationSceneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parent = QWidget()
        self.parent.file_path = None
        self.canvas = Canvas(self.parent)
        self.canvas.load_pixmap(QPixmap(100, 100))
        self.scene = CanvasAnnotationScene(self.canvas)

    def tearDown(self):
        self.canvas.deleteLater()
        self.parent.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    @staticmethod
    def shape(label, left):
        shape = Shape(label)
        for point in (
            QPointF(left, 10),
            QPointF(left + 20, 10),
            QPointF(left + 20, 30),
            QPointF(left, 30),
        ):
            shape.add_point(point)
        shape.close()
        return shape

    def test_projection_preserves_surviving_visibility_and_selects_results(self):
        first = self.shape("cat", 10)
        second = self.shape("dog", 50)
        self.canvas.load_shapes((first, second))
        before = self.scene.capture("image-a")
        first_id, second_id = (
            box.session_id for box in before.boxes
        )
        self.canvas.set_shape_visible(first, False)
        self.canvas.set_selected_shapes((second,), active_shape=second)
        changed = AnnotationSnapshot(
            image_key="image-a",
            image_size=(100, 100),
            boxes=(
                AnnotationBoxState(
                    session_id=first_id,
                    label="bird",
                    points=before.boxes[0].points,
                ),
                AnnotationBoxState(
                    session_id=3,
                    label="tree",
                    points=((70.0, 50.0), (90.0, 70.0)),
                ),
            ),
        )

        self.scene.project(
            ProjectionRequest(
                snapshot=changed,
                affected_ids=(first_id, 3, second_id),
                direction="redo",
                preserve_selection=False,
            )
        )

        projected_first, projected_new = self.canvas.shapes
        self.assertFalse(self.canvas.isVisible(projected_first))
        self.assertTrue(self.canvas.isVisible(projected_new))
        self.assertEqual(
            [shape.session_id for shape in self.canvas.selected_shapes],
            [first_id, 3],
        )
        self.assertIs(self.canvas.selected_shape, projected_new)

    def test_drag_announces_one_intent_boundary_for_many_move_events(self):
        shape = self.shape("cat", 10)
        self.canvas.load_shapes((shape,))
        started = []
        finished = []
        self.canvas.annotationGestureStarted.connect(started.append)
        self.canvas.annotationGestureFinished.connect(finished.append)
        self.canvas.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove,
            QPointF(20, 20),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        ))
        self.canvas.mousePressEvent(QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(20, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ))
        for position in (QPointF(25, 25), QPointF(30, 30)):
            self.canvas.mouseMoveEvent(QMouseEvent(
                QEvent.MouseMove,
                position,
                Qt.NoButton,
                Qt.LeftButton,
                Qt.NoModifier,
            ))
        self.canvas.mouseReleaseEvent(QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(30, 30),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        ))

        self.assertEqual(started, ["Move box"])
        self.assertEqual(finished, ["Move box"])

    def test_all_held_arrow_keys_form_one_gesture_until_last_release(self):
        shape = self.shape("cat", 10)
        self.canvas.load_shapes((shape,))
        self.canvas.set_selected_shapes((shape,), active_shape=shape)
        started = []
        finished = []
        self.canvas.annotationGestureStarted.connect(started.append)
        self.canvas.annotationGestureFinished.connect(finished.append)

        for key in (Qt.Key_Right, Qt.Key_Down):
            self.canvas.keyPressEvent(
                QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            )
        self.canvas.keyReleaseEvent(
            QKeyEvent(QEvent.KeyRelease, Qt.Key_Right, Qt.NoModifier)
        )
        self.assertEqual(finished, [])
        self.canvas.keyReleaseEvent(
            QKeyEvent(QEvent.KeyRelease, Qt.Key_Down, Qt.NoModifier)
        )

        self.assertEqual(started, ["Move box"])
        self.assertEqual(finished, ["Move box"])

    def test_arrow_gesture_commits_when_canvas_loses_focus(self):
        shape = self.shape("cat", 10)
        self.canvas.load_shapes((shape,))
        self.canvas.set_selected_shapes((shape,), active_shape=shape)
        finished = []
        self.canvas.annotationGestureFinished.connect(finished.append)
        self.canvas.keyPressEvent(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier)
        )

        self.canvas.focusOutEvent(QFocusEvent(QEvent.FocusOut))

        self.assertEqual(finished, ["Move box"])

    def test_lost_mouse_grab_cancels_active_mouse_gesture(self):
        shape = self.shape("cat", 10)
        self.canvas.load_shapes((shape,))
        canceled = []
        self.canvas.annotationGestureCanceled.connect(canceled.append)
        self.canvas._begin_annotation_gesture("Move box", source="mouse")

        QApplication.sendEvent(
            self.canvas, QEvent(QEvent.UngrabMouse)
        )

        self.assertEqual(canceled, ["Move box"])


class MainWindowHistoryIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        classes_path = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes_path, "w", encoding="utf8"):
            pass
        self.window = MainWindow(
            default_prefdef_class_file=classes_path,
            default_save_dir=self.temp_dir.name,
        )
        self.assertTrue(
            self.window.load_file(
                os.path.abspath("tests/test.512.512.bmp")
            )
        )

    def tearDown(self):
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp_dir.cleanup()

    def test_paste_undo_redo_round_trip_updates_canvas_and_menu(self):
        self.window.annotation_clipboard = [
            (
                "cat",
                ((10, 10), (30, 10), (30, 30), (10, 30)),
                None,
                None,
                False,
            ),
        ]

        self.window.paste_copied_bounding_boxes()
        self.assertEqual(len(self.window.canvas.shapes), 1)
        self.assertTrue(self.window.actions.undoAnnotation.isEnabled())

        self.window.undo_annotation()
        self.assertEqual(len(self.window.canvas.shapes), 0)
        self.assertTrue(self.window.actions.redoAnnotation.isEnabled())

        self.window.redo_annotation()
        self.assertEqual(
            [shape.label for shape in self.window.canvas.shapes],
            ["cat"],
        )

    def test_ctrl_z_routes_from_canvas_but_not_file_list(self):
        self.window.annotation_clipboard = [
            (
                "cat",
                ((10, 10), (30, 10), (30, 30), (10, 30)),
                None,
                None,
                False,
            ),
        ]
        self.window.paste_copied_bounding_boxes()
        self.window.show()
        self.window.canvas.setFocus()
        self.app.processEvents()

        QApplication.sendEvent(
            self.window.canvas,
            QKeyEvent(
                QEvent.KeyPress,
                Qt.Key_Z,
                Qt.ControlModifier,
            ),
        )
        self.assertEqual(self.window.canvas.shapes, [])

        self.window.redo_annotation()
        self.window.file_list_widget.setFocus()
        self.app.processEvents()
        QApplication.sendEvent(
            self.window.file_list_widget,
            QKeyEvent(
                QEvent.KeyPress,
                Qt.Key_Z,
                Qt.ControlModifier,
            ),
        )
        self.assertEqual(len(self.window.canvas.shapes), 1)

    def test_ctrl_z_mid_draw_restores_beginner_actions(self):
        self.window.create_shape()
        self.window.canvas.current = Shape()
        self.window.canvas.drawingPolygon.emit(True)
        self.assertTrue(self.window.annotation_editing.pending)
        self.assertFalse(self.window.actions.create.isEnabled())

        self.window.undo_annotation()

        self.assertIsNone(self.window.canvas.current)
        self.assertFalse(self.window.annotation_editing.pending)
        self.assertTrue(self.window.actions.create.isEnabled())
        self.assertTrue(self.window.canvas.editing())

    def test_shared_classes_save_refreshes_all_peer_baselines(self):
        classes = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes, "w", encoding="utf8") as output:
            output.write("cat")
        peers = []
        for name in ("first", "second"):
            image_key = os.path.join(
                self.temp_dir.name, name + ".png"
            )
            target = os.path.join(
                self.temp_dir.name, name + ".txt"
            )
            with open(target, "w", encoding="utf8") as output:
                output.write("")
            baseline = (
                target,
                (
                    (target, fingerprint_path(target)),
                    (classes, fingerprint_path(classes)),
                ),
            )
            self.window.annotation_editing.open_image(
                image_key,
                AnnotationSnapshot(image_key, (20, 20)),
                baseline,
            )
            peers.append(image_key)
        with open(classes, "w", encoding="utf8") as output:
            output.write("cat\ndog")
        updated = fingerprint_path(classes)

        self.window._propagate_resource_fingerprints(
            ((classes, updated),)
        )

        for image_key in peers:
            baseline = self.window.annotation_editing.view_image(
                image_key, touch=False
            ).saved_baseline
            self.assertEqual(
                dict(baseline.fingerprint)[classes], updated
            )


if __name__ == "__main__":
    unittest.main()
