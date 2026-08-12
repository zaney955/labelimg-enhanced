from dataclasses import replace
import unittest
from unittest import mock

from labelimg.canvas.shape import Shape
from labelimg.annotations.domain.history import (
    AnnotationBoxState,
    AnnotationHistory,
    AnnotationSnapshot,
    UnknownImageHistory,
)


def snapshot(label="cat", session_id=1, image_key="image-a"):
    boxes = ()
    if label is not None:
        boxes = (
            AnnotationBoxState(
                session_id=session_id,
                label=label,
                points=((10.0, 20.0), (110.0, 120.0)),
            ),
        )
    return AnnotationSnapshot(
        image_key=image_key,
        image_size=(512, 512),
        boxes=boxes,
    )


class AnnotationHistoryTest(unittest.TestCase):
    def test_shape_copy_is_unowned_until_a_new_edit_commits_it(self):
        shape = Shape("cat")
        shape.session_id = 41

        copied = shape.copy()

        self.assertIsNone(copied.session_id)

    def test_undo_cursor_moves_only_after_prepared_step_is_committed(self):
        history = AnnotationHistory()
        original = snapshot()
        changed = snapshot("dog")
        history.open_image("image-a", original, saved_baseline=None)

        edit = history.begin_edit("image-a", original, "Change label")
        transition = history.commit_edit(edit, changed, affected_ids=(1,))

        self.assertEqual(history.view("image-a").snapshot, changed)
        self.assertTrue(history.view("image-a").can_undo)
        self.assertEqual(transition.description, "Change label")

        step = history.prepare_undo("image-a")
        self.assertEqual(step.target_snapshot, original)
        self.assertEqual(history.view("image-a").snapshot, changed)

        history.commit_step(step)
        self.assertEqual(history.view("image-a").snapshot, original)
        self.assertTrue(history.view("image-a").can_redo)

    def test_saving_marks_the_exact_revision_without_clearing_history(self):
        history = AnnotationHistory()
        original = snapshot()
        changed = snapshot("dog")
        history.open_image("image-a", original, saved_baseline=("a.xml", "v1"))
        edit = history.begin_edit("image-a", original, "Change label")
        history.commit_edit(edit, changed, affected_ids=(1,))
        changed_revision = history.view("image-a").revision_id

        history.mark_saved(
            "image-a",
            changed_revision,
            target="a.xml",
            fingerprint="v2",
        )

        view = history.view("image-a")
        self.assertFalse(view.dirty)
        self.assertTrue(view.can_undo)
        history.commit_step(history.prepare_undo("image-a"))
        self.assertTrue(history.view("image-a").dirty)

    def test_stale_save_acknowledgement_does_not_clear_newer_revision(self):
        history = AnnotationHistory()
        original = snapshot()
        opened = history.open_image(
            "image-a", original, saved_baseline=("a.xml", "v1")
        )
        first_revision = opened.revision_id
        edit = history.begin_edit("image-a", original, "Change label")
        history.commit_edit(edit, snapshot("dog"), affected_ids=(1,))

        history.mark_saved(
            "image-a", first_revision, target="a.xml", fingerprint="v2"
        )

        view = history.view("image-a")
        self.assertTrue(view.dirty)
        self.assertEqual(view.current_target, "a.xml")

    def test_storage_target_change_is_dirty_but_not_undoable(self):
        history = AnnotationHistory()
        original = snapshot()
        history.open_image(
            "image-a",
            original,
            saved_baseline=("a.xml", "v1"),
        )

        history.set_target("image-a", "a.txt")

        view = history.view("image-a")
        self.assertTrue(view.dirty)
        self.assertFalse(view.can_undo)
        self.assertEqual(view.current_target, "a.txt")

    def test_no_op_does_not_clear_redo_but_new_edit_does(self):
        history = AnnotationHistory()
        original = snapshot()
        changed = snapshot("dog")
        history.open_image("image-a", original, saved_baseline=None)
        edit = history.begin_edit("image-a", original, "Change label")
        history.commit_edit(edit, changed, affected_ids=(1,))
        history.commit_step(history.prepare_undo("image-a"))

        no_op = history.begin_edit("image-a", original, "No change")
        self.assertIsNone(history.commit_edit(no_op, original, affected_ids=()))
        self.assertTrue(history.view("image-a").can_redo)

        replacement = snapshot("bird")
        branch = history.begin_edit("image-a", original, "Change label")
        history.commit_edit(branch, replacement, affected_ids=(1,))
        self.assertFalse(history.view("image-a").can_redo)
        self.assertEqual(history.view("image-a").snapshot, replacement)

    def test_record_allocation_failure_keeps_open_edit_and_redo_branch(self):
        history = AnnotationHistory()
        original = snapshot()
        changed = snapshot("dog")
        history.open_image("image-a", original, saved_baseline=None)
        first = history.begin_edit("image-a", original, "Change label")
        history.commit_edit(first, changed, affected_ids=(1,))
        history.commit_step(history.prepare_undo("image-a"))
        failing = history.begin_edit("image-a", original, "New branch")

        with mock.patch(
            "labelimg.annotations.domain.history._estimate_transition_bytes",
            side_effect=MemoryError("allocation failed"),
        ):
            with self.assertRaises(MemoryError):
                history.commit_edit(
                    failing,
                    snapshot("bird"),
                    affected_ids=(1,),
                )

        history.cancel_edit(failing)
        view = history.view("image-a")
        self.assertEqual(view.snapshot, original)
        self.assertTrue(view.can_redo)

    def test_each_image_keeps_an_independent_cursor(self):
        history = AnnotationHistory()
        first = snapshot()
        second = snapshot("tree", image_key="image-b")
        history.open_image("image-a", first, saved_baseline=None)
        history.open_image("image-b", second, saved_baseline=None)
        edit_a = history.begin_edit("image-a", first, "Edit A")
        history.commit_edit(edit_a, snapshot("dog"), affected_ids=(1,))
        edit_b = history.begin_edit("image-b", second, "Edit B")
        history.commit_edit(
            edit_b,
            snapshot("flower", image_key="image-b"),
            affected_ids=(1,),
        )

        history.commit_step(history.prepare_undo("image-a"))

        self.assertEqual(history.view("image-a").snapshot, first)
        self.assertEqual(
            history.view("image-b").snapshot,
            snapshot("flower", image_key="image-b"),
        )
        self.assertTrue(history.view("image-b").can_undo)

    def test_entry_limit_keeps_a_contiguous_window_and_exact_baseline(self):
        history = AnnotationHistory(max_transitions_per_image=2)
        current = snapshot()
        opened = history.open_image(
            "image-a",
            current,
            saved_baseline=("a.xml", "saved-cat"),
        )
        saved_revision = opened.revision_id
        for label in ("dog", "bird", "fox"):
            after = snapshot(label)
            edit = history.begin_edit("image-a", current, "Change label")
            history.commit_edit(edit, after, affected_ids=(1,))
            current = after

        history.commit_step(history.prepare_undo("image-a"))
        history.commit_step(history.prepare_undo("image-a"))
        view = history.view("image-a")

        self.assertEqual(view.snapshot, snapshot("dog"))
        self.assertFalse(view.can_undo)
        self.assertTrue(view.undo_boundary_evicted)
        self.assertEqual(view.saved_baseline.revision_id, saved_revision)
        self.assertTrue(view.dirty)

    def test_rebase_migrate_remove_and_clear_follow_workspace_lifecycle(self):
        history = AnnotationHistory()
        original = snapshot()
        history.open_image("image-a", original, saved_baseline=None)
        edit = history.begin_edit("image-a", original, "Change label")
        history.commit_edit(edit, snapshot("dog"), affected_ids=(1,))

        rebased = snapshot("external")
        history.rebase(
            "image-a",
            rebased,
            baseline=("external.xml", "external-fingerprint"),
        )
        self.assertFalse(history.view("image-a").can_undo)
        self.assertFalse(history.view("image-a").dirty)

        history.migrate_images(
            {"image-a": "renamed-image"},
            target_mapping={"image-a": "renamed.xml"},
            fingerprint_mapping={"image-a": "renamed-fingerprint"},
        )
        migrated = history.view("renamed-image")
        self.assertEqual(migrated.snapshot.image_key, "renamed-image")
        self.assertEqual(migrated.current_target, "renamed.xml")
        self.assertEqual(
            migrated.saved_baseline.target, "renamed.xml"
        )
        self.assertEqual(
            migrated.saved_baseline.fingerprint,
            "renamed-fingerprint",
        )
        with self.assertRaises(UnknownImageHistory):
            history.view("image-a")

        history.remove_images(("renamed-image",))
        with self.assertRaises(UnknownImageHistory):
            history.view("renamed-image")

        history.open_image("image-b", snapshot(image_key="image-b"), None)
        history.clear_workspace()
        with self.assertRaises(UnknownImageHistory):
            history.view("image-b")

    def test_review_recovery_preserves_later_box_history(self):
        history = AnnotationHistory()
        reviewed = snapshot("cat")
        reviewed = replace(
            reviewed, verified=True, questioned=False
        )
        opened = history.open_image(
            "image-a",
            reviewed,
            saved_baseline=("a.xml", "reviewed"),
        )
        changed = replace(snapshot("dog"), verified=True)
        token = history.begin_edit(
            "image-a", reviewed, "Change label"
        )
        history.commit_edit(token, changed, affected_ids=(1,))

        view = history.rewrite_review_state(
            "image-a",
            expected=(True, False),
            replacement=(False, False),
            fingerprint="recovered",
        )

        self.assertEqual(view.snapshot.boxes[0].label, "dog")
        self.assertFalse(view.snapshot.verified)
        self.assertTrue(view.dirty)
        history.commit_step(history.prepare_undo("image-a"))
        undone = history.view("image-a")
        self.assertEqual(undone.snapshot.boxes[0].label, "cat")
        self.assertFalse(undone.snapshot.verified)


if __name__ == "__main__":
    unittest.main()
