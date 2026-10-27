import os
import tempfile
import time
import unittest
import threading
from concurrent.futures import Future
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QColor, QImage

from labelimg.files.ui.image_decode_cache import DecodedImageCache, _source_token
from labelimg.annotations import fingerprint_image


class DecodedImageCacheTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.cache = DecodedImageCache(max_bytes=64 * 1024, workers=1)

    def tearDown(self):
        self.cache.shutdown()
        self.temporary.cleanup()

    def _image(self, name, color):
        path = os.path.join(self.temporary.name, name)
        image = QImage(40, 30, QImage.Format_RGBA8888)
        image.fill(QColor(color))
        self.assertTrue(image.save(path))
        return path, image

    def _replace_with_new_token(self, path, image):
        previous = _source_token(path)
        self.assertTrue(image.save(path))
        stat = os.stat(path)
        os.utime(path, ns=(
            stat.st_atime_ns,
            max(previous[3], stat.st_mtime_ns) + 1_000_000_000,
        ))
        self.assertNotEqual(_source_token(path), previous)

    def test_put_get_and_source_change_invalidation(self):
        path, image = self._image("cached.png", "red")
        self.assertTrue(self.cache.put(path, image))
        self.assertEqual(self.cache.get(path).pixelColor(0, 0), QColor("red"))

        replacement = QImage(40, 30, QImage.Format_RGBA8888)
        replacement.fill(QColor("blue"))
        self._replace_with_new_token(path, replacement)

        self.assertIsNone(self.cache.get(path))

    def test_default_budget_supports_large_neighbors_and_respects_available_memory(self):
        for available, expected in ((16 * 1024**3, 1024 * 1024**2),
                                    (1024**3, 128 * 1024**2),
                                    (None, 256 * 1024**2)):
            with patch('labelimg.files.ui.image_decode_cache._available_memory_bytes',
                       return_value=available):
                cache = DecodedImageCache()
                try:
                    self.assertEqual(cache._max_bytes, expected)
                finally:
                    cache.shutdown()

    def test_prefetch_decodes_without_ui_thread_projection(self):
        path, _image = self._image("prefetched.png", "green")
        self.cache.prefetch((path,))

        deadline = time.monotonic() + 2.0
        cached = None
        while cached is None and time.monotonic() < deadline:
            cached = self.cache.get(path)
            time.sleep(0.005)

        self.assertIsNotNone(cached)
        self.assertEqual(cached.pixelColor(0, 0), QColor("green"))

    def test_oversized_image_does_not_evict_usable_cached_neighbors(self):
        path, image = self._image('small.png', 'red')
        self.cache.put(path, image)
        large_path = os.path.join(self.temporary.name, 'large.png')
        large = QImage(200, 200, QImage.Format_RGB32)
        large.fill(QColor('blue'))
        large.save(large_path)
        self.cache.put(large_path, large)
        self.assertIsNotNone(self.cache.get(path))
        self.assertIsNone(self.cache.get(large_path))
        with patch('labelimg.files.ui.image_decode_cache._decode_image') as decode:
            self.cache.prefetch((large_path,))
            decode.assert_not_called()

    def test_demand_load_reuses_running_prefetch(self):
        path, image = self._image('shared.png', 'green')
        started, release = threading.Event(), threading.Event()
        from labelimg.files.ui.image_decode_cache import _decode_image

        def decode(*args):
            started.set()
            release.wait(1)
            return _decode_image(*args)

        with patch('labelimg.files.ui.image_decode_cache._decode_image', side_effect=decode) as calls:
            try:
                self.cache.prefetch((path,))
                self.assertTrue(started.wait(1))
            finally:
                release.set()
            loaded = self.cache.load(path)
            self.assertEqual(loaded.size(), image.size())
            self.assertEqual(loaded.pixelColor(0, 0), image.pixelColor(0, 0))
            self.assertEqual(calls.call_count, 1)

    def test_prefetch_cancelled_during_demand_handoff_retries_decode(self):
        class CancelOnResult(Future):
            def result(self, timeout=None):
                self.cancel()
                return super().result(timeout)
        path, image = self._image('cancel-handoff.png', 'green')
        from labelimg.files.ui.image_decode_cache import _path_key
        self.cache._jobs[_path_key(path)] = CancelOnResult()
        loaded = self.cache.load(path)
        self.assertEqual(loaded.pixelColor(0, 0), image.pixelColor(0, 0))

    def test_obsolete_prefetch_does_not_displace_current_neighbors(self):
        path, _image = self._image('obsolete.png', 'blue')
        started, release = threading.Event(), threading.Event()
        from labelimg.files.ui.image_decode_cache import _decode_image
        def decode(*args):
            started.set()
            release.wait(1)
            return _decode_image(*args)
        with patch('labelimg.files.ui.image_decode_cache._decode_image', side_effect=decode):
            try:
                self.cache.prefetch((path,))
                self.assertTrue(started.wait(1))
                self.cache.prefetch(())
            finally:
                release.set()
            self.cache._executor.shutdown(wait=True)
        self.assertIsNone(self.cache.get(path))

    def use_fingerprints(self):
        self.cache._fingerprint_for = fingerprint_image
        self.cache._verification_interval = 0

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(condition())

    def test_decode_binds_pixels_and_fingerprint_and_warm_hits_do_not_rehash(self):
        self.use_fingerprints()
        self.cache._verification_interval = 60
        path, _image = self._image('identity.png', 'red')
        decoded = self.cache.load(path)
        fingerprint = self.cache.cached_fingerprint(path, decoded)
        self.assertEqual(fingerprint, fingerprint_image(path, (40, 30)))
        with patch.object(self.cache, '_fingerprint_for', side_effect=AssertionError('rehash')):
            for _ in range(3):
                cached = self.cache.get(path)
                self.assertEqual(self.cache.cached_fingerprint(path, cached), fingerprint)
                self.cache.put(path, cached)
                self.assertEqual(self.cache.prepare_fingerprint(path, cached), fingerprint)

    def test_different_pixels_cannot_inherit_an_existing_fingerprint(self):
        self.use_fingerprints()
        path, _image = self._image('changed-pixels.png', 'red')
        decoded = self.cache.load(path)
        different = QImage(decoded)
        different.fill(QColor('blue'))
        self.cache.put(path, different)
        self.assertIsNone(self.cache.cached_fingerprint(path, different))

    def test_changed_source_cannot_rebind_old_pixels_to_a_new_fingerprint(self):
        self.use_fingerprints()
        path, _image = self._image('rebound.png', 'red')
        decoded = self.cache.load(path)
        replacement = QImage(40, 30, QImage.Format_RGBA8888)
        replacement.fill(QColor('blue'))
        self._replace_with_new_token(path, replacement)
        self.assertFalse(self.cache.put(path, decoded))
        with self.assertRaises(OSError):
            self.cache.prepare_fingerprint(path, decoded)

    def test_background_content_check_invalidates_replacement_with_unchanged_metadata(self):
        self.use_fingerprints()
        path = os.path.join(self.temporary.name, 'same.bmp')
        image = QImage(40, 30, QImage.Format_RGB32)
        image.fill(QColor('red'))
        self.assertTrue(image.save(path))
        stat = os.stat(path)
        # Also cover filesystems/replacement tools whose lightweight token
        # remains identical after replacement, independently of platform ctime.
        with patch('labelimg.files.ui.image_decode_cache._source_token', return_value=('same-version',)):
            first = self.cache.load(path)
            original = self.cache.cached_fingerprint(path, first)
            image.fill(QColor('blue'))
            self.assertTrue(image.save(path))
            self.assertEqual(os.stat(path).st_size, stat.st_size)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.cache.get(path)
            self.wait_until(lambda: self.cache.get(path) is None)
            latest = self.cache.load(path)
            self.assertEqual(latest.pixelColor(0, 0), QColor('blue'))
            self.assertNotEqual(self.cache.cached_fingerprint(path, latest), original)

    def test_old_background_verification_cannot_invalidate_new_pixels(self):
        self.use_fingerprints()
        path, _image = self._image('racing.png', 'red')
        self.cache.load(path)
        started, release = threading.Event(), threading.Event()
        original = self.cache._fingerprint_for
        caller = threading.get_ident()

        def verify(*args):
            captured = original(*args)
            if threading.get_ident() != caller:
                started.set()
                release.wait(2)
            return captured

        with patch.object(self.cache, '_fingerprint_for', side_effect=verify):
            try:
                self.cache.get(path)
                self.assertTrue(started.wait(1))
                self.cache.invalidate((path,))
                _path, replacement = self._image('racing.png', 'blue')
                self.cache.put(path, replacement)
                self.cache.prepare_fingerprint(path, replacement)
            finally:
                release.set()
            self.wait_until(lambda: not self.cache._verification_jobs)
        self.cache._verification_interval = 60
        latest = self.cache.get(path)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.pixelColor(0, 0), QColor('blue'))


if __name__ == "__main__":
    unittest.main()
