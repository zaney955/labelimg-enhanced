#!/usr/bin/env python
# -*- coding: utf8 -*-
import json
import ntpath
from pathlib import Path

from labelimg.constants import DEFAULT_ENCODING
import os

JSON_EXT = '.json'
ENCODE_METHOD = DEFAULT_ENCODING


def normalize_image_reference(value):
    """Return a platform-independent key for a CreateML image reference."""
    text = os.fspath(value).replace("/", "\\")
    return ntpath.normpath(text).casefold()


def image_reference_matches(reference, image_path, collection_path=None):
    """Match a CreateML record without collapsing qualified paths."""
    reference_key = normalize_image_reference(reference)
    image_key = normalize_image_reference(os.path.abspath(image_path))
    if ntpath.isabs(reference_key):
        return reference_key == image_key
    if "\\" not in reference_key:
        return ntpath.basename(image_key) == reference_key
    if image_key.endswith("\\" + reference_key):
        return True
    if collection_path is None:
        return False
    resolved = os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.abspath(collection_path)),
            *reference_key.split("\\"),
        )
    )
    return normalize_image_reference(resolved) == image_key


class CreateMLWriter:
    def __init__(self, folder_name, filename, img_size, shapes, output_file, database_src='Unknown', local_img_path=None):
        self.folder_name = folder_name
        self.filename = filename
        self.database_src = database_src
        self.img_size = img_size
        self.box_list = []
        self.local_img_path = local_img_path
        self.verified = False
        self.questioned = False
        self.shapes = shapes
        self.output_file = output_file

    def write(self):
        if os.path.isfile(self.output_file):
            with open(self.output_file, "r") as file:
                input_data = file.read()
                output_dict = json.loads(input_data)
        else:
            output_dict = []

        output_image_dict = {
            "image": self.filename,
            "annotations": [],
            "verified": bool(self.verified),
            "questioned": bool(self.questioned),
        }

        for shape in self.shapes:
            points = shape["points"]

            x1 = points[0][0]
            y1 = points[0][1]
            x2 = points[1][0]
            y2 = points[2][1]

            height, width, x, y = self.calculate_coordinates(x1, x2, y1, y2)

            shape_dict = {
                "label": shape["label"],
                "coordinates": {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height
                }
            }
            output_image_dict["annotations"].append(shape_dict)

        # check if image already in output
        exists = False
        for i in range(0, len(output_dict)):
            if normalize_image_reference(
                output_dict[i]["image"]
            ) == normalize_image_reference(output_image_dict["image"]):
                exists = True
                output_dict[i] = output_image_dict
                break

        if not exists:
            output_dict.append(output_image_dict)

        Path(self.output_file).write_text(json.dumps(output_dict), ENCODE_METHOD)

    def calculate_coordinates(self, x1, x2, y1, y2):
        if x1 < x2:
            x_min = x1
            x_max = x2
        else:
            x_min = x2
            x_max = x1
        if y1 < y2:
            y_min = y1
            y_max = y2
        else:
            y_min = y2
            y_max = y1
        width = x_max - x_min
        if width < 0:
            width = width * -1
        height = y_max - y_min
        # x and y from center of rect
        x = x_min + width / 2
        y = y_min + height / 2
        return height, width, x, y


class CreateMLReader:
    def __init__(self, json_path, file_path):
        self.json_path = json_path
        self.shapes = []
        self.verified = False
        self.questioned = False
        self.filename = os.path.basename(file_path)
        self.file_path = os.fspath(file_path)
        self.record_name = None
        self.parse_json()

    def parse_json(self):
        with open(self.json_path, "r") as file:
            input_data = file.read()

        output_dict = json.loads(input_data)
        self.verified = False
        self.questioned = False

        if len(self.shapes) > 0:
            self.shapes = []
        matches = [
            image
            for image in output_dict
            if image_reference_matches(
                image.get("image", ""), self.file_path, self.json_path
            )
        ]
        if len(matches) != 1:
            raise ValueError(
                "CreateML collection must contain exactly one matching "
                "record for %s" % self.file_path
            )
        image = matches[0]
        self.record_name = image["image"]
        self.filename = self.record_name
        self.verified = bool(
            image.get("verified", bool(image["annotations"]))
        )
        self.questioned = bool(image.get("questioned", False))
        for shape in image["annotations"]:
            self.add_shape(shape["label"], shape["coordinates"])

    def add_shape(self, label, bnd_box):
        x_min = bnd_box["x"] - (bnd_box["width"] / 2)
        y_min = bnd_box["y"] - (bnd_box["height"] / 2)

        x_max = bnd_box["x"] + (bnd_box["width"] / 2)
        y_max = bnd_box["y"] + (bnd_box["height"] / 2)

        points = [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]
        self.shapes.append((label, points, None, None, True))

    def get_shapes(self):
        return self.shapes
