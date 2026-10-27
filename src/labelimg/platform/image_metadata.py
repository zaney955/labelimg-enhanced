"""Original image geometry for annotation I/O, independent of display pixels."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageMetadata:
    pixel_width: int
    pixel_height: int
    grayscale: bool = False

    def __post_init__(self):
        if self.pixel_width <= 0 or self.pixel_height <= 0:
            raise ValueError('image dimensions must be positive')

    # The legacy format readers only need these three image properties.
    def width(self):
        return self.pixel_width

    def height(self):
        return self.pixel_height

    def isGrayscale(self):
        return self.grayscale
