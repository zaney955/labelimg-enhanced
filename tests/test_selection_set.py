import unittest

from labelimg.selection import (
    ChoiceMode,
    ChooseIntent,
    InvalidSelectionIntent,
    SceneIntent,
    SelectionSet,
)


class SelectionSetTest(unittest.TestCase):
    def setUp(self):
        self.first = object()
        self.second = object()
        self.third = object()
        self.selection = SelectionSet()
        self.selection.apply(
            SceneIntent((self.first, self.second, self.third))
        )

    def test_replace_normalises_to_scene_order_and_active_member(self):
        snapshot = self.selection.apply(
            ChooseIntent(
                (self.third, self.first),
                ChoiceMode.REPLACE,
                active=self.first,
            )
        )

        self.assertEqual(snapshot.selected, (self.first, self.third))
        self.assertIs(snapshot.active, self.first)
        self.assertTrue(snapshot.capabilities.can_bulk)
        self.assertFalse(snapshot.capabilities.can_edit_single)

    def test_toggle_adds_and_removes_one_member(self):
        self.selection.apply(
            ChooseIntent((self.second,), ChoiceMode.TOGGLE)
        )
        snapshot = self.selection.apply(
            ChooseIntent((self.first,), ChoiceMode.TOGGLE)
        )
        self.assertEqual(snapshot.selected, (self.first, self.second))

        snapshot = self.selection.apply(
            ChooseIntent((self.second,), ChoiceMode.TOGGLE)
        )
        self.assertEqual(snapshot.selected, (self.first,))
        self.assertIs(snapshot.active, self.first)
        self.assertTrue(snapshot.capabilities.can_edit_single)

    def test_overlap_cycle_selects_one_candidate_at_a_time(self):
        candidates = (self.third, self.first, self.second)

        first = self.selection.apply(
            ChooseIntent(candidates, ChoiceMode.CYCLE)
        )
        second = self.selection.apply(
            ChooseIntent(candidates, ChoiceMode.CYCLE)
        )
        third = self.selection.apply(
            ChooseIntent(candidates, ChoiceMode.CYCLE)
        )

        self.assertEqual(first.selected, (self.third,))
        self.assertEqual(second.selected, (self.first,))
        self.assertEqual(third.selected, (self.second,))

    def test_scene_change_preserves_only_surviving_selection(self):
        self.selection.apply(
            ChooseIntent(
                (self.first, self.third),
                ChoiceMode.REPLACE,
                active=self.third,
            )
        )

        snapshot = self.selection.apply(
            SceneIntent((self.first, self.second))
        )

        self.assertEqual(snapshot.selected, (self.first,))
        self.assertIs(snapshot.active, self.first)

    def test_unknown_annotation_box_is_rejected_without_partial_change(self):
        before = self.selection.snapshot

        with self.assertRaises(InvalidSelectionIntent):
            self.selection.apply(
                ChooseIntent((object(),), ChoiceMode.REPLACE)
            )

        self.assertIs(self.selection.snapshot, before)


if __name__ == "__main__":
    unittest.main()
