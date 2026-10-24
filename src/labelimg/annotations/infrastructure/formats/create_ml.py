#!/usr/bin/env python
# -*- coding: utf8 -*-
import os

from labelimg.annotations.infrastructure.formats.create_ml_collection import (
    CreateMLAnnotationCollection,
)

JSON_EXT = '.json'
ENCODE_METHOD = "utf-8"


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
        self.shapes.append((label, points, True))

    def get_shapes(self):
        return self.shapes
