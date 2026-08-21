"""Detect and repair red or yellow rectangular frame overlays."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

import cv2
import numpy as np


class FrameColor(str, Enum):
    RED = "red"
    YELLOW = "yellow"


class DetectionStrength(str, Enum):
    CONSERVATIVE = "conservative"
    STANDARD = "standard"
    LOOSE = "loose"


@dataclass(frozen=True)
class FrameRemovalOptions:
    colors: frozenset[FrameColor] = frozenset(
        (FrameColor.RED, FrameColor.YELLOW)
    )
    strength: DetectionStrength = DetectionStrength.STANDARD
    inpaint_radius: int = 3
    halo_dilate_iterations: int = 0
    normalize_near_grayscale: bool = False

    def __post_init__(self):
        colors = frozenset(FrameColor(color) for color in self.colors)
        object.__setattr__(self, "colors", colors)
        object.__setattr__(
            self,
            "strength",
            DetectionStrength(self.strength),
        )
        if not colors:
            raise ValueError("at least one frame color must be selected")
        if isinstance(self.inpaint_radius, bool) or self.inpaint_radius < 1:
            raise ValueError("inpaint_radius must be a positive integer")
        if (
            isinstance(self.halo_dilate_iterations, bool)
            or self.halo_dilate_iterations < 0
        ):
            raise ValueError(
                "halo_dilate_iterations must be a non-negative integer"
            )


@dataclass(frozen=True)
class _PackedMask:
    x: int
    y: int
    width: int
    height: int
    data: bytes

    @classmethod
    def from_full_mask(cls, mask):
        ys, xs = np.nonzero(mask)
        if not len(xs):
            raise ValueError("cannot pack an empty mask")
        left = int(xs.min())
        top = int(ys.min())
        right = int(xs.max()) + 1
        bottom = int(ys.max()) + 1
        crop = np.ascontiguousarray(
            mask[top:bottom, left:right] > 0,
            dtype=np.uint8,
        )
        return cls(
            left,
            top,
            right - left,
            bottom - top,
            np.packbits(crop.reshape(-1)).tobytes(),
        )

    def unpack(self):
        count = self.width * self.height
        bits = np.unpackbits(
            np.frombuffer(self.data, dtype=np.uint8),
            count=count,
        )
        return bits.reshape(self.height, self.width).astype(np.uint8) * 255


@dataclass(frozen=True)
class FrameCandidate:
    candidate_id: str
    color: FrameColor
    x: int
    y: int
    width: int
    height: int
    pixel_count: int
    _repair_mask: _PackedMask

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height


@dataclass(frozen=True)
class FrameRemovalAnalysis:
    image_shape: tuple[int, ...]
    candidates: tuple[FrameCandidate, ...]

    def combined_mask(self, selected_candidate_ids=None):
        height, width = self.image_shape[:2]
        mask = np.zeros((height, width), dtype=np.uint8)
        known = {
            candidate.candidate_id: candidate
            for candidate in self.candidates
        }
        selected = (
            tuple(known)
            if selected_candidate_ids is None
            else tuple(dict.fromkeys(selected_candidate_ids))
        )
        unknown = set(selected) - set(known)
        if unknown:
            raise ValueError(
                "unknown frame candidate: %s" % sorted(unknown)[0]
            )
        for candidate_id in selected:
            packed = known[candidate_id]._repair_mask
            patch = packed.unpack()
            region = mask[
                packed.y:packed.y + packed.height,
                packed.x:packed.x + packed.width,
            ]
            np.maximum(region, patch, out=region)
        return mask


@dataclass(frozen=True)
class FrameRemovalResult:
    image: np.ndarray
    mask: np.ndarray
    selected_candidate_ids: tuple[str, ...]
    normalized_grayscale: bool = False


@dataclass(frozen=True)
class _GeometryPolicy:
    minimum_side: int
    minimum_side_coverage: float
    maximum_interior_fill: float
    required_sides: int


_GEOMETRY_POLICIES = {
    DetectionStrength.CONSERVATIVE: _GeometryPolicy(18, 0.78, 0.28, 4),
    DetectionStrength.STANDARD: _GeometryPolicy(12, 0.62, 0.38, 4),
    DetectionStrength.LOOSE: _GeometryPolicy(8, 0.45, 0.52, 3),
}

_HSV_RANGES = {
    FrameColor.RED: (
        ((0, 100, 80), (10, 255, 255)),
        ((160, 100, 80), (180, 255, 255)),
    ),
    FrameColor.YELLOW: (
        ((20, 120, 120), (35, 255, 255)),
    ),
}


class ColoredFrameRemover:
    """Own frame classification, compact masks, and Telea repair."""

    def __init__(self, options=None):
        self.options = options or FrameRemovalOptions()

    def analyze(self, image):
        color_image, _alpha = _split_color_and_alpha(image)
        hsv = cv2.cvtColor(color_image, cv2.COLOR_BGR2HSV)
        candidates = []
        for color in sorted(self.options.colors, key=lambda item: item.value):
            color_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
            for lower, upper in _HSV_RANGES[color]:
                color_mask = cv2.bitwise_or(
                    color_mask,
                    cv2.inRange(
                        hsv,
                        np.asarray(lower, dtype=np.uint8),
                        np.asarray(upper, dtype=np.uint8),
                    ),
                )
            candidates.extend(self._color_candidates(color_mask, color))
        candidates.sort(
            key=lambda candidate: (
                candidate.y,
                candidate.x,
                candidate.color.value,
                candidate.width,
                candidate.height,
            )
        )
        numbered = tuple(
            replace(
                candidate,
                candidate_id="%s-%03d" % (
                    candidate.color.value,
                    index + 1,
                ),
            )
            for index, candidate in enumerate(candidates)
        )
        return FrameRemovalAnalysis(tuple(image.shape), numbered)

    def render(
        self,
        image,
        analysis,
        selected_candidate_ids=None,
    ):
        if tuple(image.shape) != analysis.image_shape:
            raise ValueError("analysis does not belong to this image")
        selected = (
            tuple(candidate.candidate_id for candidate in analysis.candidates)
            if selected_candidate_ids is None
            else tuple(dict.fromkeys(selected_candidate_ids))
        )
        mask = analysis.combined_mask(selected)
        if self.options.halo_dilate_iterations:
            mask = cv2.dilate(
                mask,
                np.ones((3, 3), dtype=np.uint8),
                iterations=self.options.halo_dilate_iterations,
            )
        if not np.any(mask):
            return FrameRemovalResult(image, mask, selected)

        color_image, alpha = _split_color_and_alpha(image)
        normalize = (
            self.options.normalize_near_grayscale
            and _is_near_grayscale_background(color_image, mask)
        )
        if normalize:
            gray = cv2.cvtColor(color_image, cv2.COLOR_BGR2GRAY)
            repaired_gray = cv2.inpaint(
                gray,
                mask,
                inpaintRadius=self.options.inpaint_radius,
                flags=cv2.INPAINT_TELEA,
            )
            repaired_color = cv2.cvtColor(
                repaired_gray,
                cv2.COLOR_GRAY2BGR,
            )
        else:
            inpainted = cv2.inpaint(
                color_image,
                mask,
                inpaintRadius=self.options.inpaint_radius,
                flags=cv2.INPAINT_TELEA,
            )
            repaired_color = color_image.copy()
            repaired_color[mask > 0] = inpainted[mask > 0]
        repaired = (
            repaired_color
            if alpha is None
            else np.dstack((repaired_color, alpha))
        )
        return FrameRemovalResult(
            repaired,
            mask,
            selected,
            normalized_grayscale=normalize,
        )

    def _color_candidates(self, raw_mask, color):
        kernel = np.ones((3, 3), dtype=np.uint8)
        connected_mask = cv2.morphologyEx(
            raw_mask,
            cv2.MORPH_CLOSE,
            kernel,
            iterations=1,
        )
        label_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            connected_mask,
            connectivity=8,
        )
        policy = _GEOMETRY_POLICIES[self.options.strength]
        image_height, image_width = raw_mask.shape
        relative_minimum = max(
            1,
            int(round(min(image_height, image_width) * 0.012)),
        )
        minimum_side = max(policy.minimum_side, relative_minimum)
        minimum_pixels = max(16, int(raw_mask.size * 0.000025))
        candidates = []
        for label in range(1, label_count):
            x, y, width, height, area = (
                int(value) for value in stats[label]
            )
            if (
                width < minimum_side
                or height < minimum_side
                or area < minimum_pixels
            ):
                continue
            component = labels[y:y + height, x:x + width] == label
            if not _looks_like_frame(component, policy):
                continue
            full_mask = np.zeros(raw_mask.shape, dtype=np.uint8)
            full_mask[y:y + height, x:x + width][component] = 255
            repair_mask = cv2.dilate(
                full_mask,
                kernel,
                iterations=2,
            )
            repair_mask = cv2.morphologyEx(
                repair_mask,
                cv2.MORPH_OPEN,
                kernel,
                iterations=1,
            )
            candidates.append(
                FrameCandidate(
                    candidate_id="",
                    color=color,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    pixel_count=int(np.count_nonzero(component)),
                    _repair_mask=_PackedMask.from_full_mask(repair_mask),
                )
            )
        return candidates


def _split_color_and_alpha(image):
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        raise TypeError("image must be an unsigned 8-bit NumPy array")
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), None
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("image must have one, three, or four channels")
    if image.shape[2] == 3:
        return image, None
    return image[:, :, :3], image[:, :, 3]


def _looks_like_frame(component, policy):
    height, width = component.shape
    band = max(2, min(14, int(round(min(height, width) * 0.18))))
    if height <= band * 2 or width <= band * 2:
        return False
    top = np.any(component[:band, :], axis=0).mean()
    bottom = np.any(component[-band:, :], axis=0).mean()
    left = np.any(component[:, :band], axis=1).mean()
    right = np.any(component[:, -band:], axis=1).mean()
    covered_sides = sum(
        coverage >= policy.minimum_side_coverage
        for coverage in (top, bottom, left, right)
    )
    interior = component[band:-band, band:-band]
    interior_fill = float(interior.mean()) if interior.size else 1.0
    return (
        covered_sides >= policy.required_sides
        and interior_fill <= policy.maximum_interior_fill
    )


def _is_near_grayscale_background(image, mask, chroma_threshold=8):
    max_side = max(image.shape[:2])
    sample_step = max(1, (max_side + 511) // 512)
    sampled_image = image[::sample_step, ::sample_step]
    sampled_mask = mask[::sample_step, ::sample_step]
    background = sampled_image[sampled_mask == 0]
    if background.size == 0:
        return False
    pixels = background.astype(np.int16)
    chroma = pixels.max(axis=1) - pixels.min(axis=1)
    return float(np.percentile(chroma, 95)) <= chroma_threshold
