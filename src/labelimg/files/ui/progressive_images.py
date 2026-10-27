"""Two bounded pixel tiers with a shared source-version contract."""
from labelimg.files.ui.image_decode_cache import DecodedImageCache, _default_cache_budget, _path_key
import threading
from labelimg.files.ui.preview_disk_cache import PreviewDiskCache
from labelimg.files.ui.preview_warmup import PreviewWarmup


class NavigationImageCache(DecodedImageCache):
    def __init__(self, *, fingerprint_for, preview_size, preview_cache_dir=None):
        budget = _default_cache_budget()
        disk = PreviewDiskCache(preview_cache_dir)
        super().__init__(max_bytes=min(256 * 1024**2, max(32 * 1024**2, budget // 4)),
                         fingerprint_for=fingerprint_for, preview_size=preview_size, disk_preview=disk)
        self._full = DecodedImageCache(max_bytes=max(1, budget - self._max_bytes),
                                      workers=1, fingerprint_for=fingerprint_for)
        self._full_lock = threading.Lock()
        self._warmup = PreviewWarmup(disk)

    def prepare_directory(self, paths):
        self._warmup.submit(paths, self.preview_size)

    def get(self, path):
        return self._full.get(path) or super().get(path)

    def put(self, path, image):
        with self._full._lock:
            prepared = self._full._prepared.get((_path_key(path), image.cacheKey()))
            known = self._full._fingerprints.get(_path_key(path))
            if image.cacheKey() in self._full._retired_pixels:
                return False
            if prepared is not None or known is not None and known[1] == image.cacheKey():
                return self._full.put(path, image)
        return super().put(path, image)

    def cached_fingerprint(self, path, image):
        return self._full.cached_fingerprint(path, image) or super().cached_fingerprint(path, image)

    def image_metadata(self, path, image):
        if self._full.cached_fingerprint(path, image) is not None:
            return self._full.image_metadata(path, image)
        return super().image_metadata(path, image)

    def load_full(self, path, expected):
        with self._full_lock:
            image = self._full.load(path)
            if image.isNull() or self._full.cached_fingerprint(path, image) != expected:
                self.invalidate((path,))
                raise OSError('image source changed before full-resolution display')
        return image

    def invalidate(self, paths):
        paths = tuple(paths)
        self._full.invalidate(paths)
        super().invalidate(paths)

    def shutdown(self):
        self._warmup.shutdown()
        self._full.shutdown()
        super().shutdown()
