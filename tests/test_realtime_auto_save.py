import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from labelimg.app import MainWindow
from labelimg.pascal_voc_io import PascalVocReader
from labelimg.shape import Shape


class RealtimeAutoSaveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.image_dir = os.path.join(self.temp_dir.name, "images")
        self.annotation_dir = os.path.join(
            self.temp_dir.name, "annotations"
        )
        os.makedirs(self.image_dir)
        os.makedirs(self.annotation_dir)

        self.image_path = os.path.join(self.image_dir, "sample.png")
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(self.image_path))

        classes_path = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass

        self.window = MainWindow(
            default_prefdef_class_file=classes_path,
            default_save_dir=self.annotation_dir,
        )
        self.window.auto_saving.setChecked(True)
        self.assertTrue(self.window.load_file(self.image_path))

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()
        self.temp_dir.cleanup()

    @property
    def annotation_path(self):
        return os.path.join(self.annotation_dir, "sample.xml")

    def add_rectangle(self, label="car"):
        shape = Shape(label=label)
        for point in (
            QPointF(10, 10),
            QPointF(40, 10),
            QPointF(40, 40),
            QPointF(10, 40),
        ):
            shape.add_point(point)
        shape.close()
        self.window.canvas.load_shapes([shape])
        self.window.add_label(shape)
        return shape

    def test_dirty_annotation_is_saved_without_changing_images(self):
        self.add_rectangle()

        self.window.set_dirty()
        QTest.qWait(300)

        self.assertTrue(os.path.isfile(self.annotation_path))
        reader = PascalVocReader(self.annotation_path)
        self.assertEqual(reader.get_shapes()[0][0], "car")
        self.assertFalse(self.window.dirty)

    def test_explicit_save_can_create_the_first_annotation_file(self):
        self.add_rectangle()
        self.window.set_dirty()

        self.window.save_file()

        self.assertTrue(os.path.isfile(self.annotation_path))
        reader = PascalVocReader(self.annotation_path)
        self.assertEqual(reader.get_shapes()[0][0], "car")

    def test_moving_and_deleting_a_shape_are_saved_in_realtime(self):
        shape = self.add_rectangle()
        self.window.set_dirty()
        QTest.qWait(300)

        shape.move_by(QPointF(5, 7))
        self.window.canvas.shapeMoved.emit()
        QTest.qWait(300)

        reader = PascalVocReader(self.annotation_path)
        self.assertEqual(reader.get_shapes()[0][1][0], (15.0, 17.0))

        self.window.canvas.select_shape(shape)
        self.window.delete_selected_shape()
        self.assertEqual(self.window.canvas.shapes, [])
        QTest.qWait(300)

        self.assertFalse(os.path.exists(self.annotation_path))

    def test_image_without_shapes_does_not_create_an_xml_file(self):
        self.window.set_dirty()
        QTest.qWait(300)

        self.assertFalse(os.path.exists(self.annotation_path))

    def test_explicit_save_without_shapes_does_not_create_an_xml_file(self):
        self.window.set_dirty()

        self.window.save_file()

        self.assertFalse(os.path.exists(self.annotation_path))
        self.assertFalse(self.window.dirty)

    def test_deleting_one_of_two_shapes_keeps_the_remaining_annotation(self):
        first_shape = self.add_rectangle("car")
        second_shape = first_shape.copy()
        second_shape.label = "truck"
        second_shape.move_by(QPointF(20, 20))
        self.window.canvas.shapes.append(second_shape)
        self.window.add_label(second_shape)
        self.window.set_dirty()
        QTest.qWait(300)

        self.window.canvas.select_shape(second_shape)
        self.window.delete_selected_shape()
        QTest.qWait(300)

        self.assertTrue(os.path.exists(self.annotation_path))
        reader = PascalVocReader(self.annotation_path)
        self.assertEqual(
            [shape[0] for shape in reader.get_shapes()],
            ["car"],
        )

    def test_disabling_auto_save_leaves_changes_dirty(self):
        self.window.auto_saving.setChecked(False)
        self.add_rectangle()

        self.window.set_dirty()
        QTest.qWait(300)

        self.assertFalse(os.path.exists(self.annotation_path))
        self.assertTrue(self.window.dirty)

    def test_copying_a_shape_is_saved_in_realtime(self):
        shape = self.add_rectangle()
        self.window.set_dirty()
        QTest.qWait(300)

        self.window.canvas.select_shape(shape)
        self.window.copy_selected_shape()
        QTest.qWait(300)

        reader = PascalVocReader(self.annotation_path)
        self.assertEqual(len(reader.get_shapes()), 2)


if __name__ == "__main__":
    unittest.main()
