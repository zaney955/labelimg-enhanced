import io
import os
import tempfile
import unittest

import numpy as np
from PIL import Image, PngImagePlugin

from labelimg.image_tools.image_file_codec import (
    ImageFileCodec,
    UnsupportedImageFile,
)


class ImageFileCodecTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.codec = ImageFileCodec()

    def tearDown(self):
        self.temporary.cleanup()

    def path(self, name):
        return os.path.join(self.temporary.name, name)

    def test_jpeg_round_trip_preserves_dimensions_exif_icc_and_dpi(self):
        path = self.path("source.jpg")
        image = Image.new("RGB", (64, 48), (100, 110, 120))
        exif = Image.Exif()
        exif[271] = "LabelImg Camera"
        exif[274] = 1
        icc = b"test-icc-profile"
        image.save(
            path,
            quality=87,
            subsampling=1,
            exif=exif,
            icc_profile=icc,
            dpi=(144, 144),
        )

        loaded = self.codec.load(path)
        changed = loaded.pixels.copy()
        changed[10:20, 10:20] = (12, 34, 56)
        encoded = self.codec.encode(loaded, changed)
        output = Image.open(io.BytesIO(encoded))

        self.assertEqual(output.format, "JPEG")
        self.assertEqual(output.size, (64, 48))
        self.assertEqual(output.getexif().get(271), "LabelImg Camera")
        self.assertEqual(output.getexif().get(274), 1)
        self.assertEqual(output.info.get("icc_profile"), icc)
        self.assertEqual(tuple(round(value) for value in output.info["dpi"]), (144, 144))

    def test_png_round_trip_preserves_alpha_and_text_metadata(self):
        path = self.path("source.png")
        pixels = np.zeros((32, 40, 4), dtype=np.uint8)
        pixels[:, :, :3] = (10, 20, 30)
        pixels[:, :, 3] = np.arange(40, dtype=np.uint8)
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("dataset", "acceptance")
        Image.fromarray(pixels, "RGBA").save(path, pnginfo=metadata, dpi=(96, 96))

        loaded = self.codec.load(path)
        encoded = self.codec.encode(loaded, loaded.pixels)
        output = Image.open(io.BytesIO(encoded))

        self.assertEqual(output.format, "PNG")
        self.assertEqual(output.mode, "RGBA")
        self.assertEqual(output.info.get("dataset"), "acceptance")
        self.assertTrue(np.array_equal(np.asarray(output)[:, :, 3], pixels[:, :, 3]))

    def test_exif_orientation_is_baked_into_pixels_and_normalized(self):
        path = self.path("oriented.jpg")
        pixels = np.zeros((20, 30, 3), dtype=np.uint8)
        pixels[:5, :5] = (255, 0, 0)
        exif = Image.Exif()
        exif[274] = 6
        Image.fromarray(pixels, "RGB").save(path, exif=exif)

        loaded = self.codec.load(path)
        encoded = self.codec.encode(loaded, loaded.pixels)

        self.assertEqual(loaded.size, (20, 30))
        with Image.open(io.BytesIO(encoded)) as output:
            self.assertEqual(output.size, (20, 30))
            self.assertEqual(output.getexif().get(274), 1)

    def test_bmp_round_trip_keeps_bmp_format_and_dimensions(self):
        path = self.path("source.bmp")
        Image.new("RGB", (31, 27), "white").save(path)

        loaded = self.codec.load(path)
        output = Image.open(io.BytesIO(self.codec.encode(loaded, loaded.pixels)))

        self.assertEqual(output.format, "BMP")
        self.assertEqual(output.size, (31, 27))

    def test_rejects_unsupported_extension_and_sixteen_bit_png(self):
        gif = self.path("source.gif")
        Image.new("RGB", (10, 10), "white").save(gif)
        with self.assertRaises(UnsupportedImageFile):
            self.codec.load(gif)

        sixteen_bit = self.path("source.png")
        Image.fromarray(
            np.full((10, 10), 1024, dtype=np.uint16),
        ).save(sixteen_bit)
        with self.assertRaises(UnsupportedImageFile):
            self.codec.load(sixteen_bit)


if __name__ == "__main__":
    unittest.main()
