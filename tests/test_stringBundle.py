import os
import unittest

import labelimg.resources
from labelimg.stringBundle import StringBundle

class TestStringBundle(unittest.TestCase):

    def test_loadDefaultBundle_withoutError(self):
        str_bundle = StringBundle.get_bundle('en')
        self.assertEqual(str_bundle.get_string("openDir"), 'Open Image Directory…', 'Fail to load the default bundle')

    def test_fallback_withoutError(self):
        str_bundle = StringBundle.get_bundle('zh-TW')
        self.assertEqual(str_bundle.get_string("openDir"), '打开图像目录…', 'All Chinese locales use Simplified Chinese')

    def test_setInvaleLocaleToEnv_printErrorMsg(self):
        prev_lc = os.environ.get('LC_ALL')
        prev_lang = os.environ.get('LANG')
        os.environ['LC_ALL'] = 'UTF-8'
        os.environ['LANG'] = 'UTF-8'
        try:
            str_bundle = StringBundle.get_bundle()
            self.assertEqual(str_bundle.get_string("openDir"), 'Open Image Directory…', 'Fail to load the default bundle')
        finally:
            if prev_lc is None:
                os.environ.pop('LC_ALL', None)
            else:
                os.environ['LC_ALL'] = prev_lc
            if prev_lang is None:
                os.environ.pop('LANG', None)
            else:
                os.environ['LANG'] = prev_lang


if __name__ == '__main__':
    unittest.main()
