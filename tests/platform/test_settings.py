#!/usr/bin/env python
import os
import tempfile
import unittest

from labelimg.annotations.domain.model import AnnotationFormat
from labelimg.platform.settings import Settings

__author__ = 'TzuTaLin'

class TestSettings(unittest.TestCase):

    def test_basic(self):
        settings = Settings()
        settings['test0'] = 'hello'
        settings['test1'] = 10
        settings['test2'] = [0, 2, 3]
        self.assertEqual(settings.get('test3', 3), 3)
        self.assertEqual(settings.save(), True)

        settings.load()
        self.assertEqual(settings.get('test0'), 'hello')
        self.assertEqual(settings.get('test1'), 10)

        settings.reset()

    def assert_legacy_label_format_loads(self, module_name):
        legacy_settings = (
            b'(dp0\nVlabelFileFormat\np1\n'
            + b'c' + module_name.encode('ascii')
            + b'\nLabelFileFormat\np2\n'
            b'(I2\ntp3\nRp4\ns.'
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings_path = os.path.join(
                temporary_directory,
                '.labelImgSettings.pkl',
            )
            with open(settings_path, 'wb') as settings_file:
                settings_file.write(legacy_settings)

            settings = Settings()
            settings.path = settings_path

            self.assertTrue(settings.load())
            self.assertIs(
                settings['labelFileFormat'],
                AnnotationFormat.YOLO,
            )

    def test_loads_label_format_saved_by_legacy_libs_package(self):
        self.assert_legacy_label_format_loads('libs.labelFile')

    def test_loads_label_format_saved_by_legacy_labelimg_package(self):
        self.assert_legacy_label_format_loads('labelimg.labelFile')


if __name__ == '__main__':
    unittest.main()
