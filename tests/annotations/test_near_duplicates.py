import unittest

from PyQt5.QtCore import QPointF

from labelimg.canvas import (
    CATEGORY_CONFLICT,
    DUPLICATE_LABEL_RISK,
    detect_near_duplicate_clusters,
)
from labelimg.canvas.shape import Shape


def rectangle(label, left, top, right, bottom, session_id=None):
    shape = Shape(label)
    shape.session_id = session_id
    for point in (
        QPointF(left, top),
        QPointF(right, top),
        QPointF(right, bottom),
        QPointF(left, bottom),
    ):
        shape.add_point(point)
    shape.close()
    return shape


class NearDuplicateDetectionTest(unittest.TestCase):
    def test_exact_and_pairwise_edge_close_boxes_cluster(self):
        exact = rectangle("cat", 10, 10, 110, 110, "a")
        shifted = rectangle("cat", 11, 9, 111, 109, "b")
        clusters = detect_near_duplicate_clusters((exact, shifted))

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].members, (exact, shifted))
        self.assertEqual(clusters[0].risk, DUPLICATE_LABEL_RISK)

    def test_large_containment_and_partial_overlap_do_not_cluster(self):
        outer = rectangle("cat", 0, 0, 200, 200)
        inner = rectangle("cat", 20, 20, 180, 180)
        partial = rectangle("cat", 100, 0, 300, 200)

        self.assertEqual(
            detect_near_duplicate_clusters((outer, inner, partial)),
            (),
        )

    def test_every_corresponding_edge_must_be_close(self):
        first = rectangle("cat", 0, 0, 100, 100)
        different_right = rectangle("cat", 1, 1, 104, 101)

        self.assertEqual(
            detect_near_duplicate_clusters((first, different_right)),
            (),
        )

    def test_two_percent_threshold_uses_smaller_axis_and_one_pixel_floor(self):
        large = rectangle("cat", 0, 0, 100, 100)
        at_large_limit = rectangle("cat", 2, 2, 102, 102)
        over_large_limit = rectangle("cat", 2.1, 0, 102.1, 100)
        small = rectangle("cat", 0, 0, 20, 20)
        at_small_floor = rectangle("cat", 1, 1, 21, 21)

        self.assertEqual(
            len(detect_near_duplicate_clusters((large, at_large_limit))),
            1,
        )
        self.assertEqual(
            detect_near_duplicate_clusters((large, over_large_limit)),
            (),
        )
        self.assertEqual(
            len(detect_near_duplicate_clusters((small, at_small_floor))),
            1,
        )

    def test_different_labels_form_category_conflict(self):
        cat = rectangle("cat", 0, 0, 50, 50)
        dog = rectangle("dog", 1, 0, 51, 50)

        clusters = detect_near_duplicate_clusters((cat, dog))

        self.assertEqual(clusters[0].risk, CATEGORY_CONFLICT)

    def test_chain_is_split_into_disjoint_strict_clusters(self):
        first = rectangle("cat", 0.0, 0, 100.0, 100, "a")
        middle = rectangle("cat", 1.5, 0, 101.5, 100, "b")
        last = rectangle("cat", 3.0, 0, 103.0, 100, "c")

        clusters = detect_near_duplicate_clusters((first, middle, last))

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].members, (first, middle))

    def test_cluster_members_remain_in_document_order(self):
        first = rectangle("cat", 0, 0, 100, 100, "a")
        second = rectangle("cat", 0, 0, 100, 100, "b")
        third = rectangle("cat", 0, 0, 100, 100, "c")

        cluster = detect_near_duplicate_clusters(
            (third, first, second)
        )[0]

        self.assertEqual(cluster.members, (third, first, second))
        self.assertEqual(cluster.ordinal(first), 2)

    def test_large_exact_cluster_keeps_every_member(self):
        shapes = tuple(
            rectangle("cat", 0, 0, 100, 100, "shape-%d" % index)
            for index in range(1000)
        )

        clusters = detect_near_duplicate_clusters(shapes)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].members, shapes)


if __name__ == "__main__":
    unittest.main()
