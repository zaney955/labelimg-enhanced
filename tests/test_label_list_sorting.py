import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRect
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from labelimg.app import LabelListItemDelegate, MainWindow
from labelimg.shape import Shape


class LabelListSortingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        classes_path = os.path.join(self.temp_dir.name, "classes.txt")
        with open(classes_path, "w", encoding="utf-8"):
            pass

        self.window = MainWindow(default_prefdef_class_file=classes_path)

    def tearDown(self):
        self.window.deleteLater()
        self.app.processEvents()
        self.temp_dir.cleanup()

    def label_names(self):
        return [
            self.window.label_list.item(index).text()
            for index in range(self.window.label_list.count())
        ]

    def render_first_item(self, selected):
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 180, 30)
        option.state = QStyle.State_Enabled
        if selected:
            option.state |= QStyle.State_Selected
        option.widget = self.window.label_list

        image = QImage(180, 30, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        self.window.label_list.itemDelegate().paint(
            painter,
            option,
            self.window.label_list.model().index(0, 0),
        )
        painter.end()
        return image

    def test_labels_are_sorted_by_name_when_added(self):
        for label in ("zebra", "apple", "middle"):
            self.window.add_label(Shape(label=label))

        self.assertEqual(self.label_names(), ["apple", "middle", "zebra"])

    def test_labels_are_resorted_after_renaming(self):
        for label in ("apple", "middle", "zebra"):
            self.window.add_label(Shape(label=label))

        self.window.label_list.item(2).setText("aardvark")

        self.assertEqual(self.label_names(), ["aardvark", "apple", "middle"])

    def test_selected_label_keeps_its_background_and_gets_a_blue_border(self):
        self.window.add_label(Shape(label="apple"))
        item = self.window.label_list.item(0)
        item.setBackground(QColor(210, 160, 90))

        unselected_image = self.render_first_item(selected=False)
        selected_image = self.render_first_item(selected=True)

        self.assertEqual(
            selected_image.pixelColor(160, 15),
            unselected_image.pixelColor(160, 15),
        )
        self.assertEqual(
            selected_image.pixelColor(90, 1),
            LabelListItemDelegate.selected_border_color,
        )


if __name__ == "__main__":
    unittest.main()
