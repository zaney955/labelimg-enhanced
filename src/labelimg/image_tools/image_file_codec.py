"""Read and encode supported image-tool files without losing metadata."""

from __future__ import annotations

from dataclasses import dataclass
import io
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


class ImageFileCodec:
    """Hide supported-format, channel-order, and metadata handling."""

    _FORMATS = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".bmp": "BMP",
    }

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
                processing_image = ImageOps.exif_transpose(image)
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
                image.load()
                if image.format != loaded.format:
                    raise UnsupportedImageFile(
                        "encoded result changed image format"
                    )
                if image.size != expected_size:
                    raise UnsupportedImageFile(
                        "encoded result changed image dimensions"
                    )
                expected_mode = "RGB" if loaded.format == "JPEG" else loaded.mode
                if image.mode != expected_mode:
                    raise UnsupportedImageFile(
                        "encoded result changed image channel mode"
                    )
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
