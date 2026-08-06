"""Prepare image-tool previews and commit-ready replacement bytes."""

from __future__ import annotations

from dataclasses import dataclass
import os

import numpy as np

from labelimg.annotation_storage import fingerprint_path
from labelimg.image_tools.colored_frame_removal import (
    ColoredFrameRemover,
    FrameRemovalOptions,
)
from labelimg.image_tools.image_file_codec import (
    ImageFileCodec,
    UnsupportedImageFile,
)
from labelimg.image_tools.recoverable_replacement import (
    PreparedImageReplacement,
)


class ImageToolPreparationError(RuntimeError):
    pass


class UnsupportedImageToolTarget(ImageToolPreparationError):
    pass


@dataclass(frozen=True)
class PreparedImageToolResult:
    path: str
    options: FrameRemovalOptions
    candidates: tuple
    selected_candidate_ids: tuple[str, ...]
    original_pixels: np.ndarray
    result_pixels: np.ndarray
    mask: np.ndarray
    replacement: PreparedImageReplacement | None
    normalized_grayscale: bool
    expected_fingerprint: object
    _loaded: object
    _analysis: object

    @property
    def changed(self):
        return self.replacement is not None


class ImageToolProcessor:
    """Own file loading, analysis reuse, rendering, and safe encoding."""

    def __init__(self, codec=None):
        self._codec = codec or ImageFileCodec()

    def prepare(self, path, options=None):
        path = os.path.abspath(os.fspath(path))
        options = options or FrameRemovalOptions()
        expected = fingerprint_path(path)
        if not expected.exists:
            raise ImageToolPreparationError(
                "the image no longer exists: %s" % path
            )
        try:
            loaded = self._codec.load(path)
            if fingerprint_path(path) != expected:
                raise ImageToolPreparationError(
                    "the image changed while it was being loaded"
                )
            remover = ColoredFrameRemover(options)
            analysis = remover.analyze(loaded.pixels)
            return self._render(
                loaded,
                analysis,
                options,
                expected,
                None,
            )
        except ImageToolPreparationError:
            raise
        except UnsupportedImageFile as error:
            raise UnsupportedImageToolTarget(str(error)) from error
        except Exception as error:
            raise ImageToolPreparationError(str(error)) from error

    def select_candidates(self, prepared, candidate_ids):
        candidate_ids = tuple(dict.fromkeys(candidate_ids))
        expected = prepared.expected_fingerprint
        if fingerprint_path(prepared.path) != expected:
            raise ImageToolPreparationError(
                "the image changed after its preview was prepared"
            )
        try:
            return self._render(
                prepared._loaded,
                prepared._analysis,
                prepared.options,
                expected,
                candidate_ids,
            )
        except ImageToolPreparationError:
            raise
        except Exception as error:
            raise ImageToolPreparationError(str(error)) from error

    def _render(
        self,
        loaded,
        analysis,
        options,
        expected,
        selected_candidate_ids,
    ):
        remover = ColoredFrameRemover(options)
        rendered = remover.render(
            loaded.pixels,
            analysis,
            selected_candidate_ids,
        )
        selected = rendered.selected_candidate_ids
        replacement = None
        if np.any(rendered.mask):
            content = self._codec.encode(loaded, rendered.image)
            if fingerprint_path(loaded.path) != expected:
                raise ImageToolPreparationError(
                    "the image changed while its result was being prepared"
                )
            replacement = PreparedImageReplacement(
                loaded.path,
                expected,
                content,
            )
        return PreparedImageToolResult(
            path=loaded.path,
            options=options,
            candidates=analysis.candidates,
            selected_candidate_ids=selected,
            original_pixels=loaded.pixels.copy(),
            result_pixels=rendered.image,
            mask=rendered.mask,
            replacement=replacement,
            normalized_grayscale=rendered.normalized_grayscale,
            expected_fingerprint=expected,
            _loaded=loaded,
            _analysis=analysis,
        )
