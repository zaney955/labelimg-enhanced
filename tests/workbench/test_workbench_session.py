import os
import unittest

from labelimg.workbench.session import (
    TransitionBlocker,
    TransitionFacts,
    TransitionRequirement,
    WorkbenchSession,
)


class WorkbenchSessionTest(unittest.TestCase):
    def test_current_image_changes_only_through_an_authorized_transition(self):
        session = WorkbenchSession("relative.png")
        self.assertEqual(
            session.image_path,
            os.path.abspath("relative.png"),
        )
        self.assertFalse(hasattr(session, "replace_active"))
        ticket = session.authorize_transition(
            session.plan_transition("next.png", TransitionFacts()),
            TransitionFacts(),
        )
        session.commit_transition(ticket)
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

    def test_transition_plan_orders_requirements_and_ticket_is_single_use(self):
        session = WorkbenchSession("current.png")
        plan = session.plan_transition(
            "next.png",
            TransitionFacts(
                crop_active=True,
                annotation_edit_open=True,
                external_conflicts=("labels.xml",),
                dirty_images=("current.png",),
            ),
        )

        self.assertEqual(
            plan.requirements,
            (
                TransitionRequirement.RESOLVE_CROP,
                TransitionRequirement.FINISH_ANNOTATION_EDIT,
                TransitionRequirement.RESOLVE_EXTERNAL_CONFLICTS,
                TransitionRequirement.RESOLVE_DIRTY_ANNOTATIONS,
            ),
        )
        ticket = session.authorize_transition(
            session.plan_transition("next.png", TransitionFacts()),
            TransitionFacts(),
        )
        self.assertEqual(
            session.commit_transition(ticket),
            os.path.abspath("next.png"),
        )
        with self.assertRaises(RuntimeError):
            session.commit_transition(ticket)


if __name__ == "__main__":
    unittest.main()
