#!/usr/bin/env python
# -*- coding: utf8 -*-
import os

from labelimg.constants import DEFAULT_ENCODING
from labelimg.create_ml_collection import (
    CreateMLAnnotationCollection,
    CreateMLRecordIdentity,
    normalize_image_reference,
)

JSON_EXT = '.json'
ENCODE_METHOD = DEFAULT_ENCODING


def image_reference_matches(reference, image_path, collection_path=None):
    """Compatibility wrapper for complete-reference identity matching."""
    collection_path = collection_path or os.curdir
    return CreateMLRecordIdentity(
        collection_path,
        reference,
    ).matches(image_path)


class CreateMLWriter:
    def __init__(
        self,
        folder_name,
        filename,
        img_size,
        shapes,
        output_file,
        database_src='Unknown',
        local_img_path=None,
    ):
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
        collection = CreateMLAnnotationCollection.read(
            self.output_file,
            missing_ok=True,
        )
        collection.upsert_annotation_record(
            self.filename,
            self.shapes,
            verified=self.verified,
            questioned=self.questioned,
        ).write(self.output_file)

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
        collection = CreateMLAnnotationCollection.read(
            self.json_path,
            strict=True,
        )
        self.verified = False
        self.questioned = False
        self.shapes = []
        record = collection.resolve(self.file_path)
        self.record_name = record.reference
        self.filename = self.record_name
        self.verified = record.verified
        self.questioned = record.questioned
        self.shapes.extend(record.reader_shapes)

    def add_shape(self, label, bnd_box):
        x_min = bnd_box["x"] - (bnd_box["width"] / 2)
        y_min = bnd_box["y"] - (bnd_box["height"] / 2)

        x_max = bnd_box["x"] + (bnd_box["width"] / 2)
        y_max = bnd_box["y"] + (bnd_box["height"] / 2)

        points = [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]
        self.shapes.append((label, points, None, None, True))

    def get_shapes(self):
        return self.shapes
