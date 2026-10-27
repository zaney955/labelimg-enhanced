"""Workbench projection of source-bound previews and delayed full pixels."""
from PyQt5.QtCore import QTimer
from labelimg.files.ui.navigation_loader import NavigationLoader
from labelimg.files.ui.image_decode_cache import _source_token


class ProgressiveImageActions:
    def _navigation_preview_size(self):
        viewport = self.scroll_area.viewport()
        density = viewport.devicePixelRatioF()
        return (max(640, round(viewport.width() * density * 1.25)),
                max(480, round(viewport.height() * density * 1.25)))

    def _cancel_image_refinement(self):
        self._refinement_generation = getattr(self, '_refinement_generation', 0) + 1
        self._refinement_path = None
        timer = getattr(self, '_refinement_timer', None)
        if timer is not None:
            timer.stop()
        loader = getattr(self, '_refinement_loader', None)
        if loader is not None:
            loader.cancel()

    def _has_image_preview(self):
        return bool(self.file_path and not self.image.isNull()
                    and self.image.size() != self.canvas.pixmap_size)

    def _schedule_image_refinement(self):
        if not self._has_image_preview():
            return
        timer = getattr(self, '_refinement_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(self._start_image_refinement)
            self._refinement_timer = timer
        timer.start()

    def _note_navigation_activity(self, path):
        # Reset on every request, including coalesced repeats and discrete taps.
        self._cancel_image_refinement()
        projection = getattr(self, '_file_list_projection', None)
        if projection is not None:
            for direction in (1, -1):
                if path == projection.adjacent_visible(self.file_path, direction):
                    self._navigation_direction = direction
                    break
        self._schedule_image_refinement()
        self._prefetch_adjacent_images()

    def _start_image_refinement(self):
        if (not self._has_image_preview() or getattr(self, '_navigation_load_path', None)
                or self.file_path == getattr(self, '_refinement_path', None)):
            return
        loader = getattr(self, '_refinement_loader', None)
        if loader is None:
            loader = NavigationLoader(self._ensure_image_decode_cache(), self)
            loader.completed.connect(self._image_refinement_ready)
            self._refinement_loader = loader
        self._refinement_generation = getattr(self, '_refinement_generation', 0) + 1
        self._refinement_path = self.file_path
        loader.submit(self._refinement_generation, self.file_path, self._loaded_image_fingerprint)

    def _image_refinement_ready(self, generation, path, image, token):
        if (generation != self._refinement_generation or path != self.file_path
                or path != self._refinement_path):
            return
        self._refinement_path = None
        cache = self._ensure_image_decode_cache()
        if (image.isNull() or token != _source_token(path)
                or cache.cached_fingerprint(path, image) != self._loaded_image_fingerprint
                or image.size() != self.canvas.pixmap_size):
            self.status_translation('status.errorReading', detail=path, important=True)
            return
        self._project_refined_image(image)

    def _project_refined_image(self, image):
        # Pixel refinement is not a document transition: preserve edits/view.
        self.image = image
        self.canvas.replace_pixmap(
            self._activate_display_adjustment_source(image, self.file_path),
            logical_size=self.canvas.pixmap_size)

    def _request_image_detail(self):
        if (self._has_image_preview()
                and self.canvas.pixmap_size.width() * self.canvas.scale
                    * self.canvas.devicePixelRatioF() > self.image.width()):
            self._start_image_refinement()

    def _ensure_full_image(self):
        """Pixel tools need the original; annotation I/O uses source metadata."""
        if not self._has_image_preview():
            return
        self._cancel_image_refinement()
        path, expected = self.file_path, self._loaded_image_fingerprint
        cache = self._ensure_image_decode_cache()
        image = self._run_image_preparation(lambda _cancelled: cache.load_full(path, expected))
        if self.file_path != path or self._loaded_image_fingerprint != expected:
            raise OSError('active image changed while preparing original pixels')
        self._project_refined_image(image)
