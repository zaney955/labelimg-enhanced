import os
import unittest

from labelimg.workbench.session import (
    TransitionBlocker,
    WorkbenchSession,
)


class WorkbenchSessionTest(unittest.TestCase):
    def test_current_image_is_normalised_and_replaceable(self):
        session = WorkbenchSession("relative.png")
        self.assertEqual(
            session.image_path,
            os.path.abspath("relative.png"),
        )
        session.replace_active("next.png")
        self.assertEqual(session.image_path, os.path.abspath("next.png"))

    def test_transition_blockers_are_structured_and_deterministic(self):
        session = WorkbenchSession()
        session.set_blocked(TransitionBlocker.IMAGE_CROP)
        session.set_blocked(TransitionBlocker.ANNOTATION_EDIT)
        readiness = session.transition_readiness()
        self.assertFalse(readiness.allowed)
        self.assertEqual(
            readiness.blockers,
            (
                TransitionBlocker.ANNOTATION_EDIT,
                TransitionBlocker.IMAGE_CROP,
            ),
        )
        with self.assertRaises(RuntimeError):
            session.activate("blocked.png")


if __name__ == "__main__":
    unittest.main()
