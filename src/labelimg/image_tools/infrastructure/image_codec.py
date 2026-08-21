"""Read and encode supported image-tool files without losing metadata."""

from __future__ import annotations

from dataclasses import dataclass
import io
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageOps, JpegImagePlugin, PngImagePlugin


class UnsupportedImageFile(ValueError):
    pass


@dataclass(frozen=True)
class LoadedImage:
    path: str
    format: str
    mode: str
    pixels: np.ndarray
    exif: bytes
    icc_profile: bytes | None
    dpi: tuple | None
    text: tuple[tuple[str, str], ...]
    jpeg_quantization: object = None
    jpeg_subsampling: int | None = None

    @property
    def size(self):
        return self.pixels.shape[1], self.pixels.shape[0]


@dataclass(frozen=True)
class LoadedImagePreview:
    """Display-oriented, bounded pixels plus the full source dimensions."""

    path: str
    format: str
    mode: str
    source_size: tuple[int, int]
    pixels: np.ndarray

    @property
    def size(self):
        return self.source_size

    @property
    def preview_size(self):
        return self.pixels.shape[1], self.pixels.shape[0]


@dataclass(frozen=True)
class ImageFileInfo:
    path: str
    format: str
    mode: str
    size: tuple[int, int]


@dataclass(frozen=True)
class EncodedImageTransform:
    path: str
    source_size: tuple[int, int]
    output_size: tuple[int, int]
    content: bytes


@dataclass(frozen=True)
class _EncodingProfile:
    path: str
    format: str
    mode: str
    exif: bytes
    icc_profile: bytes | None
    dpi: tuple | None
    text: tuple[tuple[str, str], ...]
    jpeg_quantization: object
    jpeg_subsampling: int | None


class ImageFileCodec:
    """Hide supported-format, channel-order, and metadata handling."""

    _FORMATS = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".bmp": "BMP",
    }

    def inspect(self, path):
        """Read validated image identity and display size without decoding."""
        path = os.path.abspath(os.fspath(path))
        extension = os.path.splitext(path)[1].lower()
        expected_format = self._FORMATS.get(extension)
        if expected_format is None:
            raise UnsupportedImageFile(
                "only 8-bit JPEG, PNG, and BMP images are supported"
            )
        try:
            with Image.open(path) as image:
                if image.format != expected_format:
                    raise UnsupportedImageFile(
                        "the file content does not match its extension"
                    )
                if image.mode not in ("L", "RGB", "RGBA"):
                    raise UnsupportedImageFile(
                        "only 8-bit L, RGB, and RGBA images are supported"
                    )
                orientation = _orientation_from_info(image)
                size = (
                    (image.height, image.width)
                    if orientation in (5, 6, 7, 8)
                    else tuple(image.size)
                )
                mode = image.mode
        except UnsupportedImageFile:
            raise
        except Exception as error:
            raise UnsupportedImageFile(str(error)) from error
        return ImageFileInfo(path, expected_format, mode, size)

    def load(self, path):
        path = os.path.abspath(os.fspath(path))
        extension = os.path.splitext(path)[1].lower()
        expected_format = self._FORMATS.get(extension)
        if expected_format is None:
            raise UnsupportedImageFile(
                "only 8-bit JPEG, PNG, and BMP images are supported"
            )
        try:
            with Image.open(path) as image:
                image.load()
                if image.format != expected_format:
                    raise UnsupportedImageFile(
                        "the file content does not match its extension"
                    )
                if image.mode not in ("L", "RGB", "RGBA"):
                    raise UnsupportedImageFile(
                        "only 8-bit L, RGB, and RGBA images are supported"
                    )
                exif = image.getexif().tobytes()
                icc_profile = image.info.get("icc_profile")
                dpi = image.info.get("dpi")
                text = tuple(
                    sorted(
                        (str(key), str(value))
                        for key, value in getattr(image, "text", {}).items()
                    )
                )
                quantization = (
                    {
                        key: tuple(values)
                        for key, values in image.quantization.items()
                    }
                    if image.format == "JPEG"
                    and getattr(image, "quantization", None)
                    else None
                )
                subsampling = (
                    JpegImagePlugin.get_sampling(image)
                    if image.format == "JPEG"
                    else None
                )
                ImageOps.exif_transpose(image, in_place=True)
                processing_image = image
                pixels = _pil_to_processing_array(processing_image)
                processing_mode = processing_image.mode
        except UnsupportedImageFile:
            raise
        except Exception as error:
            raise UnsupportedImageFile(str(error)) from error
        return LoadedImage(
            path=path,
            format=expected_format,
            mode=processing_mode,
            pixels=pixels,
            exif=exif,
            icc_profile=icc_profile,
            dpi=dpi,
            text=text,
            jpeg_quantization=quantization,
            jpeg_subsampling=subsampling,
        )

    def load_preview(self, path, *, max_pixels=1_500_000):
        """Decode a display preview without retaining full-resolution pixels.

        JPEG decoders are asked for a native reduced-resolution draft before
        loading. Other supported formats are bounded immediately after decode.
        The returned ``size`` always describes the display-oriented source.
        """
        path = os.path.abspath(os.fspath(path))
        extension = os.path.splitext(path)[1].lower()
        expected_format = self._FORMATS.get(extension)
        if expected_format is None:
            raise UnsupportedImageFile(
                "only 8-bit JPEG, PNG, and BMP images are supported"
            )
        try:
            max_pixels = int(max_pixels)
            if max_pixels < 1:
                raise ValueError("preview pixel budget must be positive")
            with Image.open(path) as image:
                if image.format != expected_format:
                    raise UnsupportedImageFile(
                        "the file content does not match its extension"
                    )
                if image.mode not in ("L", "RGB", "RGBA"):
                    raise UnsupportedImageFile(
                        "only 8-bit L, RGB, and RGBA images are supported"
                    )
                orientation = int(image.getexif().get(274, 1) or 1)
                encoded_size = tuple(image.size)
                source_size = (
                    (encoded_size[1], encoded_size[0])
                    if orientation in (5, 6, 7, 8)
                    else encoded_size
                )
                preview_size = _bounded_size(source_size, max_pixels)
                decoder_size = (
                    (preview_size[1], preview_size[0])
                    if orientation in (5, 6, 7, 8)
                    else preview_size
                )
                image.draft(image.mode, decoder_size)
                image.thumbnail(decoder_size, Image.Resampling.BILINEAR)
                ImageOps.exif_transpose(image, in_place=True)
                processing_image = image
                processing_image.thumbnail(
                    preview_size,
                    Image.Resampling.BILINEAR,
                )
                pixels = _pil_to_processing_array(processing_image)
                processing_mode = processing_image.mode
        except UnsupportedImageFile:
            raise
        except Exception as error:
            raise UnsupportedImageFile(str(error)) from error
        return LoadedImagePreview(
            path=path,
            format=expected_format,
            mode=processing_mode,
            source_size=source_size,
            pixels=pixels,
        )

    def transform(self, path, operation, *, crop_box=None):
        """Encode one geometry change without a full NumPy round trip."""
        path = os.path.abspath(os.fspath(path))
        extension = os.path.splitext(path)[1].lower()
        expected_format = self._FORMATS.get(extension)
        if expected_format is None:
            raise UnsupportedImageFile(
                "only 8-bit JPEG, PNG, and BMP images are supported"
            )
        try:
            with Image.open(path) as image:
                image.load()
                if image.format != expected_format:
                    raise UnsupportedImageFile(
                        "the file content does not match its extension"
                    )
                if image.mode not in ("L", "RGB", "RGBA"):
                    raise UnsupportedImageFile(
                        "only 8-bit L, RGB, and RGBA images are supported"
                    )
                profile = _encoding_profile(path, image)
                ImageOps.exif_transpose(image, in_place=True)
                source_size = tuple(image.size)
                profile = _EncodingProfile(
                    path=profile.path,
                    format=profile.format,
                    mode=image.mode,
                    exif=profile.exif,
                    icc_profile=profile.icc_profile,
                    dpi=profile.dpi,
                    text=profile.text,
                    jpeg_quantization=profile.jpeg_quantization,
                    jpeg_subsampling=profile.jpeg_subsampling,
                )
                transpose = {
                    "rotate-clockwise": Image.Transpose.ROTATE_270,
                    "rotate-counterclockwise": Image.Transpose.ROTATE_90,
                    "rotate-180": Image.Transpose.ROTATE_180,
                    "flip-horizontal": Image.Transpose.FLIP_LEFT_RIGHT,
                    "flip-vertical": Image.Transpose.FLIP_TOP_BOTTOM,
                }.get(str(operation))
                if transpose is not None:
                    result = image.transpose(transpose)
                elif operation == "crop":
                    box = tuple(int(value) for value in crop_box or ())
                    if (
                        len(box) != 4
                        or box[0] < 0
                        or box[1] < 0
                        or box[2] <= box[0]
                        or box[3] <= box[1]
                        or box[2] > source_size[0]
                        or box[3] > source_size[1]
                    ):
                        raise ValueError("crop region is outside the image")
                    result = image.crop(box)
                else:
                    raise ValueError("unsupported image transform: %s" % operation)
                encoded_size = tuple(result.size)
                output = io.BytesIO()
                result.save(
                    output,
                    format=profile.format,
                    **self._save_arguments(profile, encoded_size),
                )
                content = output.getvalue()
                self._validate_encoded(profile, content, encoded_size)
        except (UnsupportedImageFile, ValueError):
            raise
        except Exception as error:
            raise UnsupportedImageFile(str(error)) from error
        return EncodedImageTransform(
            path=path,
            source_size=source_size,
            output_size=encoded_size,
            content=content,
        )

    def encode(self, loaded, pixels, *, output_size=None):
        pixels = np.asarray(pixels)
        if pixels.dtype != np.uint8:
            raise UnsupportedImageFile("processed pixels must remain 8-bit")
        expected_size = loaded.size if output_size is None else tuple(output_size)
        actual_size = (pixels.shape[1], pixels.shape[0])
        if actual_size != expected_size:
            raise UnsupportedImageFile(
                "processed pixels do not match the expected output dimensions"
            )
        image = _processing_array_to_pil(pixels, loaded.mode)
        output = io.BytesIO()
        arguments = self._save_arguments(loaded, expected_size)
        image.save(output, format=loaded.format, **arguments)
        content = output.getvalue()
        self._validate_encoded(loaded, content, expected_size)
        return content

    @staticmethod
    def _save_arguments(loaded, output_size):
        arguments = {}
        if loaded.exif:
            exif = Image.Exif()
            exif.load(loaded.exif)
            width, height = output_size
            for tag in (256, 40962):
                if tag in exif:
                    exif[tag] = width
            for tag in (257, 40963):
                if tag in exif:
                    exif[tag] = height
            # Processing arrays are always in display orientation, so the
            # encoded image must not ask readers to rotate those pixels again.
            if 274 in exif:
                exif[274] = 1
            arguments["exif"] = exif.tobytes()
        if loaded.icc_profile:
            arguments["icc_profile"] = loaded.icc_profile
        if loaded.dpi:
            arguments["dpi"] = loaded.dpi
        if loaded.format == "JPEG":
            if loaded.jpeg_quantization:
                arguments["qtables"] = loaded.jpeg_quantization
            else:
                arguments["quality"] = 95
            if loaded.jpeg_subsampling is not None:
                arguments["subsampling"] = loaded.jpeg_subsampling
        elif loaded.format == "PNG" and loaded.text:
            png_info = PngImagePlugin.PngInfo()
            for key, value in loaded.text:
                png_info.add_text(key, value)
            arguments["pnginfo"] = png_info
        return arguments

    @staticmethod
    def _validate_encoded(loaded, content, expected_size):
        try:
            with Image.open(io.BytesIO(content)) as image:
                if image.format != loaded.format:
                    raise UnsupportedImageFile(
                        "encoded result changed image format"
                    )
                if image.size != expected_size:
                    raise UnsupportedImageFile(
                        "encoded result changed image dimensions"
                    )
                if image.mode != loaded.mode:
                    raise UnsupportedImageFile(
                        "encoded result changed image channel mode"
                    )
                image.verify()
        except UnsupportedImageFile:
            raise
        except Exception as error:
            raise UnsupportedImageFile(
                "encoded result could not be validated: %s" % error
            ) from error


def _pil_to_processing_array(image):
    pixels = np.asarray(image)
    if image.mode == "L":
        return np.ascontiguousarray(pixels)
    if image.mode == "RGB":
        return cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
    return cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGRA)


def _processing_array_to_pil(pixels, mode):
    if mode == "L":
        if pixels.ndim != 2:
            raise UnsupportedImageFile(
                "grayscale sources must remain single-channel"
            )
        return Image.fromarray(np.ascontiguousarray(pixels))
    if mode == "RGB":
        if pixels.ndim != 3 or pixels.shape[2] != 3:
            raise UnsupportedImageFile("RGB sources must remain three-channel")
        rgb = cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)
    if pixels.ndim != 3 or pixels.shape[2] != 4:
        raise UnsupportedImageFile("RGBA sources must retain their alpha channel")
    rgba = cv2.cvtColor(pixels, cv2.COLOR_BGRA2RGBA)
    return Image.fromarray(rgba)


def _encoding_profile(path, image):
    quantization = (
        {
            key: tuple(values)
            for key, values in image.quantization.items()
        }
        if image.format == "JPEG" and getattr(image, "quantization", None)
        else None
    )
    subsampling = (
        JpegImagePlugin.get_sampling(image)
        if image.format == "JPEG"
        else None
    )
    return _EncodingProfile(
        path=path,
        format=image.format,
        mode=image.mode,
        exif=image.getexif().tobytes(),
        icc_profile=image.info.get("icc_profile"),
        dpi=image.info.get("dpi"),
        text=tuple(
            sorted(
                (str(key), str(value))
                for key, value in getattr(image, "text", {}).items()
            )
        ),
        jpeg_quantization=quantization,
        jpeg_subsampling=subsampling,
    )


def _orientation_from_info(image):
    encoded_exif = image.info.get("exif")
    if not encoded_exif:
        return 1
    exif = Image.Exif()
    exif.load(encoded_exif)
    return int(exif.get(274, 1) or 1)


def _bounded_size(size, max_pixels):
    width, height = (int(value) for value in size)
    if width < 1 or height < 1:
        raise UnsupportedImageFile("image dimensions must be positive")
    if width * height <= max_pixels:
        return width, height
    scale = math.sqrt(max_pixels / float(width * height))
    bounded = (
        max(1, int(width * scale)),
        max(1, int(height * scale)),
    )
    while bounded[0] * bounded[1] > max_pixels:
        if bounded[0] >= bounded[1]:
            bounded = (bounded[0] - 1, bounded[1])
        else:
            bounded = (bounded[0], bounded[1] - 1)
    return bounded
