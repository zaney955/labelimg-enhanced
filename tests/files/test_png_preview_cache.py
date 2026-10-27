"""PNG previews are disposable, source-bound and independent of full decode RAM."""
import os
import hashlib
from pathlib import Path
import tempfile
import time
import threading
from concurrent.futures import CancelledError
import unittest
from unittest.mock import patch

from PyQt5.QtGui import QColor, QImage
from labelimg.annotations import fingerprint_image
from labelimg.files.ui.progressive_images import NavigationImageCache


class PngPreviewCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = str(self.root / 'source.png')
        self.disk = self.root / 'previews'
        image = QImage(3000, 2000, QImage.Format_ARGB32)
        image.fill(QColor(200, 20, 30, 100))
        self.assertTrue(image.save(self.path))
        self.caches = []

    def cache(self):
        cache = NavigationImageCache(fingerprint_for=fingerprint_image,
                                     preview_size=(640, 480), preview_cache_dir=self.disk)
        self.caches.append(cache)
        return cache

    def tearDown(self):
        for cache in self.caches:
            cache.shutdown()
            cache._executor.shutdown(wait=True, cancel_futures=True)
            cache._warmup.join()
        self.temp.cleanup()

    def test_new_session_uses_lossless_disk_preview_without_source_decode(self):
        before = Path(self.path).read_bytes()
        first = self.cache().load(self.path)
        self.assertLess(first.width(), 3000)
        second_cache = self.cache()
        with patch('labelimg.files.ui.image_decode_cache._read_source_pixels',
                   side_effect=AssertionError('source decoded twice')):
            second = second_cache.load(self.path)
        self.assertEqual(first, second)
        self.assertEqual(second.pixelColor(10, 10).alpha(), 100)
        self.assertEqual(second_cache.image_metadata(self.path, second).width(), 3000)
        self.assertEqual(second_cache.cached_fingerprint(self.path, second),
                         fingerprint_image(self.path, (3000, 2000)))
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_same_path_and_preserved_token_cannot_reuse_old_content(self):
        with patch('labelimg.files.ui.image_decode_cache._source_token', return_value=('same',)):
            self.cache().load(self.path)
            image = QImage(3000, 2000, QImage.Format_RGB32)
            image.fill(QColor('blue')); image.save(self.path)
            cache = self.cache()
            fresh = cache.load(self.path)
            self.assertEqual(fresh.pixelColor(0, 0), QColor('blue'))
            hint = cache._disk_preview._hint_path(self.path, ('same',), fresh.size())
            expected = cache._disk_preview.key(hashlib.sha256(Path(self.path).read_bytes()).hexdigest(), fresh.size())
            self.assertEqual(hint.read_text(), expected)

    def test_corrupt_disk_entry_falls_back_to_source(self):
        expected = self.cache().load(self.path)
        files = list(self.disk.glob('*.preview'))
        self.assertTrue(files)
        files[0].write_bytes(b'broken')
        self.assertEqual(self.cache().load(self.path), expected)

    def test_unwritable_cache_is_optional(self):
        self.disk.write_text('not a directory')
        self.assertFalse(self.cache().load(self.path).isNull())

    def test_large_png_prefetch_uses_preview_budget(self):
        cache = self.cache()
        cache._max_bytes = 4 * 1024**2  # Full pixels need 24 MB, preview fits.
        cache.prefetch((self.path,))
        deadline = time.monotonic() + 4
        while cache.get(self.path) is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNotNone(cache.get(self.path))

    def test_directory_warmup_builds_disk_previews_without_filling_image_lru(self):
        cache = self.cache()
        cache.prepare_directory((self.path,))
        self.assertTrue(cache._warmup.wait(5))
        self.assertTrue(list(self.disk.glob('*.preview')))
        self.assertEqual(cache._entry_bytes, 0)
        self.assertIsNotNone(self.cache().load(self.path))

    def test_disk_quota_and_clear_only_touch_cache_entries(self):
        from labelimg.files.ui.preview_disk_cache import PreviewDiskCache
        disk = PreviewDiskCache(self.disk, max_entries=2)
        image = QImage(20, 20, QImage.Format_RGBA8888); image.fill(QColor('red'))
        for value in range(4):
            disk.store(f'{value:064x}', image)
        self.assertEqual(len(list(self.disk.glob('*.preview'))), 2)
        unrelated = self.disk / 'notes.txt'; unrelated.write_text('keep')
        disk.prune(clear=True)
        self.assertEqual(list(self.disk.glob('*.preview')), [])
        self.assertEqual(unrelated.read_text(), 'keep')

    def test_low_memory_skips_speculation_but_allows_explicit_load(self):
        from labelimg.files.ui.image_decode_cache import _HEAVY_DECODES
        with patch.object(_HEAVY_DECODES, 'allows_background', return_value=False):
            cache = self.cache()
            cache._max_bytes = 4 * 1024**2
            cache.prefetch((self.path,))
            self.assertEqual(cache._jobs, {})
            self.assertFalse(cache.load(self.path).isNull())

    def test_decode_budget_prioritizes_demand_and_cancels_waiters(self):
        from labelimg.files.ui.decode_budget import DecodeBudget
        budget = DecodeBudget(lambda: 4 * 1024**3)
        order, errors = [], []
        stop = threading.Event()
        def run(name, speculative, cancelled=lambda: False):
            try:
                with budget.acquire(100, speculative, cancelled):
                    order.append(name)
            except CancelledError:
                errors.append(name)
        with budget.acquire(100):
            back = threading.Thread(target=run, args=('background', True))
            front = threading.Thread(target=run, args=('foreground', False))
            cancel = threading.Thread(target=run, args=('cancelled', True, stop.is_set))
            back.start(); front.start(); cancel.start()
            deadline = time.monotonic() + 2
            while not budget._foreground_waiters and time.monotonic() < deadline:
                time.sleep(.001)
            stop.set(); cancel.join(2)
        front.join(2); back.join(2)
        self.assertEqual(order, ['foreground', 'background'])
        self.assertEqual(errors, ['cancelled'])

    def test_switching_directory_discards_old_warmup_queue(self):
        from labelimg.files.ui.preview_warmup import PreviewWarmup
        from labelimg.files.ui.preview_disk_cache import PreviewDiskCache
        worker = PreviewWarmup(PreviewDiskCache(self.disk))
        began, release = threading.Event(), threading.Event()
        seen, cancelled_results = [], []
        def decode(path, _token, _fp, _bounds, _disk, cancelled, _speculative):
            seen.append(path)
            if len(seen) == 1:
                began.set(); release.wait(2)
                cancelled_results.append(cancelled())
        try:
            with patch('labelimg.files.ui.preview_warmup._decode_image', side_effect=decode):
                worker.submit((self.path,) * 4, (640, 480))
                self.assertTrue(began.wait(2))
                worker.submit((self.path,), (640, 480))
                release.set()
                self.assertTrue(worker.wait(3))
            self.assertEqual(len(seen), 2)
            self.assertEqual(cancelled_results, [True])
        finally:
            release.set(); worker.shutdown(); worker.join()

    def test_concurrent_instances_share_one_source_decode(self):
        from concurrent.futures import ThreadPoolExecutor
        from labelimg.files.ui.image_decode_cache import _read_source_pixels
        first, second = self.cache(), self.cache()
        def slow(reader):
            time.sleep(.05)
            return _read_source_pixels(reader)
        with patch('labelimg.files.ui.image_decode_cache._read_source_pixels', side_effect=slow) as read:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(cache.load, self.path) for cache in (first, second)]
                images = [future.result() for future in futures]
            self.assertEqual(read.call_count, 1)
            self.assertEqual(images[0], images[1])

    def test_disk_hit_rechecks_source_before_binding_fingerprint(self):
        self.cache().load(self.path)
        cache = self.cache()
        def replace(path, dimensions):
            image = QImage(3000, 2000, QImage.Format_RGB32)
            image.fill(QColor('blue')); image.save(path)
            return fingerprint_image(path, dimensions)
        with patch.object(cache, '_fingerprint_for', side_effect=replace), \
             patch('labelimg.files.ui.image_decode_cache._source_token', return_value=('same',)):
            with self.assertRaises(OSError):
                cache.load(self.path)

    def test_demand_waiting_for_shared_content_cannot_deadlock_background_owner(self):
        from labelimg.files.ui.decode_budget import DecodeBudget
        budget = DecodeBudget(lambda: 4 * 1024**3)
        finished = threading.Event()
        def owner():
            with budget.acquire(100, True, key='owner'):
                finished.set()
        thread = threading.Thread(target=owner)
        with budget.prioritize('waiting-for-content-lock'):
            thread.start()
            completed = finished.wait(.5)
        thread.join(2)
        self.assertTrue(completed, 'content owner blocked by a waiter outside the decode queue')

    def test_ready_disk_preview_does_not_wait_for_a_preparation_lock(self):
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        cache = self.cache()
        cache.load(self.path)
        key = next(self.disk.glob('*.preview')).stem
        reader = self.cache()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with cache._disk_preview.single_flight(key, lambda: False):
                future = pool.submit(reader.load, self.path)
                try:
                    image = future.result(timeout=1)
                except TimeoutError:
                    image = None
            future.result(timeout=3)
        self.assertIsNotNone(image, 'a ready preview waited behind unrelated background preparation')

    def test_reopened_directory_skips_prepared_sources_but_display_still_checks_content(self):
        self.cache().load(self.path)
        cache = self.cache()
        with patch('labelimg.files.ui.preview_warmup._decode_image') as decode:
            cache.prepare_directory((self.path,))
            self.assertTrue(cache._warmup.wait(2))
            decode.assert_not_called()
        with patch.object(cache, '_fingerprint_for', wraps=fingerprint_image) as fingerprint:
            cache.load(self.path)
            fingerprint.assert_called_once_with(self.path, (3000, 2000))

    def test_disk_hit_prefetch_does_not_require_full_png_memory(self):
        from labelimg.files.ui.image_decode_cache import _HEAVY_DECODES
        self.cache().load(self.path)
        cache = self.cache(); cache._max_bytes = 4 * 1024**2
        with patch.object(_HEAVY_DECODES, 'allows_background', side_effect=lambda size: size <= 4 * 1024**2):
            cache.prefetch((self.path,))
            deadline = time.monotonic() + 2
            while cache.get(self.path) is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIsNotNone(cache.get(self.path))


if __name__ == '__main__':
    unittest.main()
