import unittest

from labelimg.selection import (
    InvalidSelectionIntent,
    SelectionSet,
)


class SelectionSetTest(unittest.TestCase):
    def setUp(self):
        self.first = object()
        self.second = object()
        self.third = object()
        self.selection = SelectionSet()
        self.selection.set_scene(
            (self.first, self.second, self.third)
        )

    def test_replace_normalises_to_scene_order_and_active_member(self):
        snapshot = self.selection.replace(
            (self.third, self.first),
            active=self.first,
        )

        self.assertEqual(snapshot.selected, (self.first, self.third))
        self.assertIs(snapshot.active, self.first)
        self.assertTrue(snapshot.capabilities.can_bulk)
        self.assertFalse(snapshot.capabilities.can_edit_single)

    def test_toggle_adds_and_removes_one_member(self):
        self.selection.toggle(self.second)
        snapshot = self.selection.toggle(self.first)
        self.assertEqual(snapshot.selected, (self.first, self.second))

        snapshot = self.selection.toggle(self.second)
        self.assertEqual(snapshot.selected, (self.first,))
        self.assertIs(snapshot.active, self.first)
        self.assertTrue(snapshot.capabilities.can_edit_single)

    def test_repeating_replace_has_no_hidden_overlap_state(self):
        first = self.selection.replace((self.second,), active=self.second)
        second = self.selection.replace((self.second,), active=self.second)

        self.assertIs(second, first)
        self.assertEqual(second.selected, (self.second,))
        self.assertIs(second.active, self.second)

    def test_multi_selection_can_have_no_arbitrary_active_member(self):
        snapshot = self.selection.replace((self.first, self.second))

        self.assertEqual(snapshot.selected, (self.first, self.second))
        self.assertIsNone(snapshot.active)

    def test_scene_change_preserves_only_surviving_selection(self):
        self.selection.replace(
            (self.first, self.third),
            active=self.third,
        )

        snapshot = self.selection.set_scene((self.first, self.second))

        self.assertEqual(snapshot.selected, (self.first,))
        self.assertIs(snapshot.active, self.first)

    def test_unknown_annotation_box_is_rejected_without_partial_change(self):
        before = self.selection.snapshot

        with self.assertRaises(InvalidSelectionIntent):
            self.selection.replace((object(),))

        self.assertIs(self.selection.snapshot, before)

    def test_explicit_scene_selection_clears_previous_members(self):
        self.selection.replace((self.first, self.second))

        snapshot = self.selection.set_scene(
            (self.first, self.second, self.third),
            selected=(),
        )

        self.assertEqual(snapshot.selected, ())
        self.assertIsNone(snapshot.active)


if __name__ == "__main__":
    unittest.main()
