"""Deterministic, explainable image-quality checks and persistent cache."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
import tempfile

import cv2
import numpy as np

from labelimg.annotations import ResourceFingerprint, fingerprint_path
from labelimg.image_tools.infrastructure.image_codec import ImageFileCodec


@dataclass(frozen=True)
class ImageQualityPolicy:
    min_width: int = 640
    min_height: int = 480
    max_aspect_ratio: float = 4.0
    workspace_aspect_factor: float = 2.0
    blur_variance: float = 80.0
    dark_mean: float = 40.0
    overexposed_mean: float = 235.0

    @classmethod
    def standard(cls):
        return cls()

    def with_overrides(self, **changes):
        return replace(self, **changes)

    @property
    def key(self):
        payload = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ImageQualityFinding:
    code: str
    severity: str
    metric: float | None
    threshold: float | None
    explanation: str


@dataclass(frozen=True)
class ImageQualityResult:
    path: str
    fingerprint: ResourceFingerprint
    policy_key: str
    size: tuple[int, int] | None
    findings: tuple[ImageQualityFinding, ...]
    error: str | None = None

    @property
    def has_findings(self):
        return bool(self.findings)


class ImageQualityScanner:
    """Run local metrics without changing image bytes."""

    ANALYSIS_MAX_PIXELS = 2_000_000

    def __init__(self, codec=None):
        self._codec = codec or ImageFileCodec()

    def scan(self, path, policy=None):
        policy = policy or ImageQualityPolicy.standard()
        path = os.path.abspath(os.fspath(path))
        fingerprint = fingerprint_path(path)
        try:
            loaded = self._codec.load_preview(
                path,
                max_pixels=self.ANALYSIS_MAX_PIXELS,
            )
        except Exception as error:
            return ImageQualityResult(
                path,
                fingerprint,
                policy.key,
                None,
                (ImageQualityFinding(
                    "unreadable",
                    "error",
                    None,
                    None,
                    "The image cannot be decoded: %s" % error,
                ),),
                str(error),
            )
        width, height = loaded.size
        pixels = loaded.pixels
        if pixels.ndim == 2:
            luminance = pixels
        else:
            luminance = cv2.cvtColor(
                pixels[..., :3],
                cv2.COLOR_BGR2GRAY,
            )
        mean = float(np.mean(luminance))
        laplacian_variance = float(
            cv2.Laplacian(luminance, cv2.CV_32F).var()
        )
        aspect = max(width / height, height / width)
        findings = []
        if width < policy.min_width or height < policy.min_height:
            findings.append(ImageQualityFinding(
                "low_resolution", "warning", float(min(width, height)),
                float(min(policy.min_width, policy.min_height)),
                "Image size %dx%d is below the %dx%d policy minimum."
                % (width, height, policy.min_width, policy.min_height),
            ))
        if aspect > policy.max_aspect_ratio:
            findings.append(ImageQualityFinding(
                "aspect_anomaly", "warning", aspect,
                policy.max_aspect_ratio,
                "Aspect ratio %.2f exceeds the policy limit %.2f."
                % (aspect, policy.max_aspect_ratio),
            ))
        if laplacian_variance < policy.blur_variance:
            findings.append(ImageQualityFinding(
                "blur", "warning", laplacian_variance,
                policy.blur_variance,
                "Normalized Laplacian variance %.2f is below %.2f."
                % (laplacian_variance, policy.blur_variance),
            ))
        if mean < policy.dark_mean:
            findings.append(ImageQualityFinding(
                "dark", "warning", mean, policy.dark_mean,
                "Mean luminance %.2f is below %.2f."
                % (mean, policy.dark_mean),
            ))
        if mean > policy.overexposed_mean:
            findings.append(ImageQualityFinding(
                "overexposed", "warning", mean,
                policy.overexposed_mean,
                "Mean luminance %.2f is above %.2f."
                % (mean, policy.overexposed_mean),
            ))
        return ImageQualityResult(
            path,
            fingerprint,
            policy.key,
            (width, height),
            tuple(findings),
        )

    def scan_many(
        self,
        paths,
        policy=None,
        *,
        should_cancel=lambda: False,
        progress=lambda _completed, _total: None,
    ):
        policy = policy or ImageQualityPolicy.standard()
        paths = tuple(os.path.abspath(os.fspath(path)) for path in paths)
        results = {}
        for index, path in enumerate(paths, 1):
            if should_cancel():
                return None
            results[path] = self.scan(path, policy)
            progress(index, len(paths))
        usable = [
            result for result in results.values() if result.size is not None
        ]
        if len(usable) < 3:
            return results
        ratios = np.asarray(
            [result.size[0] / result.size[1] for result in usable],
            dtype=np.float64,
        )
        median = float(np.median(ratios))
        for result in usable:
            ratio = result.size[0] / result.size[1]
            factor = max(ratio / median, median / ratio)
            if factor <= policy.workspace_aspect_factor:
                continue
            if any(item.code == "aspect_anomaly" for item in result.findings):
                continue
            finding = ImageQualityFinding(
                "aspect_anomaly", "warning", factor,
                policy.workspace_aspect_factor,
                "Aspect differs from the workspace median by %.2fx (limit %.2fx)."
                % (factor, policy.workspace_aspect_factor),
            )
            results[result.path] = replace(
                result, findings=result.findings + (finding,)
            )
        return results


class ImageQualityCache:
    """JSON cache keyed by absolute path, fingerprint, and policy."""

    def __init__(self, path):
        self.path = os.path.abspath(os.fspath(path))

    def get(self, image_path, policy):
        image_path = os.path.abspath(os.fspath(image_path))
        data = self._read()
        value = data.get(self._key(image_path))
        if not value or value.get("policy_key") != policy.key:
            return None
        fingerprint = fingerprint_path(image_path)
        if value.get("fingerprint") != asdict(fingerprint):
            return None
        return self._deserialize(value)

    def summaries(self, image_paths, policy):
        """Bulk-load cache summaries without hashing image contents."""
        data = self._read()
        results = {}
        for image_path in image_paths:
            image_path = os.path.abspath(os.fspath(image_path))
            value = data.get(self._key(image_path))
            if not value or value.get("policy_key") != policy.key:
                continue
            try:
                results[image_path] = self._deserialize(value)
            except (KeyError, TypeError, ValueError):
                continue
        return results

    def put(self, result):
        data = self._read()
        data[self._key(result.path)] = self._serialize(result)
        self._write(data)

    def put_many(self, results):
        data = self._read()
        for result in results:
            data[self._key(result.path)] = self._serialize(result)
        self._write(data)

    def clear(self):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as stream:
                value = json.load(stream)
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, OSError, ValueError):
            return {}

    def _write(self, data):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        descriptor, staged = tempfile.mkstemp(
            prefix="quality-", suffix=".json", dir=directory
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, sort_keys=True)
            os.replace(staged, self.path)
        finally:
            if os.path.exists(staged):
                os.remove(staged)

    @staticmethod
    def _serialize(result):
        return {
            "path": result.path,
            "fingerprint": asdict(result.fingerprint),
            "policy_key": result.policy_key,
            "size": list(result.size) if result.size is not None else None,
            "findings": [asdict(item) for item in result.findings],
            "error": result.error,
        }

    @staticmethod
    def _deserialize(value):
        return ImageQualityResult(
            value["path"],
            ResourceFingerprint(**value["fingerprint"]),
            value["policy_key"],
            tuple(value["size"]) if value.get("size") is not None else None,
            tuple(ImageQualityFinding(**item) for item in value["findings"]),
            value.get("error"),
        )
