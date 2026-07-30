import os
import tempfile
import unittest

from labelimg.create_ml_io import CreateMLReader, CreateMLWriter
from labelimg.pascal_voc_io import PascalVocReader, PascalVocWriter

class TestPascalVocRW(unittest.TestCase):

    def test_upper(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_file = os.path.join(temporary_directory, 'test.xml')
            writer = PascalVocWriter(
                'tests',
                'test',
                (512, 512, 1),
                local_img_path='tests/test.512.512.bmp',
            )
            difficult = 1
            writer.add_bnd_box(60, 40, 430, 504, 'person', difficult)
            writer.add_bnd_box(113, 40, 450, 403, 'face', difficult)
            writer.save(output_file)

            reader = PascalVocReader(output_file)
            shapes = reader.get_shapes()

        person_bnd_box = shapes[0]
        face = shapes[1]
        self.assertEqual(person_bnd_box[0], 'person')
        self.assertEqual(person_bnd_box[1], [(60, 40), (430, 40), (430, 504), (60, 504)])
        self.assertEqual(face[0], 'face')
        self.assertEqual(face[1], [(113, 40), (450, 40), (450, 403), (113, 403)])


class TestCreateMLRW(unittest.TestCase):

    @staticmethod
    def write_annotations(output_file):
        person = {'label': 'person', 'points': ((65, 45), (420, 45), (420, 512), (65, 512))}
        face = {'label': 'face', 'points': ((245, 250), (350, 250), (350, 365), (245, 365))}
        shapes = [person, face]
        writer = CreateMLWriter(
            'tests',
            'test.512.512.bmp',
            (512, 512, 1),
            shapes,
            output_file,
            local_img_path='tests/test.512.512.bmp',
        )
        writer.write()

    def test_a_write(self):
        import json

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_file = os.path.join(temporary_directory, 'tests.json')
            self.write_annotations(output_file)
            with open(output_file, "r", encoding="utf-8") as file:
                input_data = file.read()

        data_dict = json.loads(input_data)[0]

        self.assertEqual('test.512.512.bmp', data_dict['image'], 'filename not correct in .json')
        self.assertEqual(2, len(data_dict['annotations']), 'output file contains to less annotations')
        face = data_dict['annotations'][1]
        self.assertEqual('face', face['label'], 'label name is wrong')
        face_coords = face['coordinates']
        self.assertEqual(105, face_coords['width'], 'calculated width is wrong')
        self.assertEqual(115, face_coords['height'], 'calculated height is wrong')
        self.assertEqual(297.5, face_coords['x'], 'calculated x is wrong')
        self.assertEqual(307.5, face_coords['y'], 'calculated y is wrong')

    def test_b_read(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_file = os.path.join(temporary_directory, 'tests.json')
            self.write_annotations(output_file)
            reader = CreateMLReader(output_file, 'tests/test.512.512.bmp')
            shapes = reader.get_shapes()
        face = shapes[1]

        self.assertEqual(2, len(shapes), 'shape count is wrong')
        self.assertEqual('face', face[0], 'label is wrong')

        face_coords = face[1]
        x_min = face_coords[0][0]
        x_max = face_coords[1][0]
        y_min = face_coords[0][1]
        y_max = face_coords[2][1]

        self.assertEqual(245, x_min, 'xmin is wrong')
        self.assertEqual(350, x_max, 'xmax is wrong')
        self.assertEqual(250, y_min, 'ymin is wrong')
        self.assertEqual(365, y_max, 'ymax is wrong')


if __name__ == '__main__':
    unittest.main()
