#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compatibility facade for extensions using the historical StringBundle."""
from labelimg.i18n import normalize_language
from labelimg.translations import CATALOGS


class StringBundle:

    __create_key = object()

    def __init__(self, create_key, locale_str):
        assert(create_key == StringBundle.__create_key), "StringBundle must be created using StringBundle.getBundle"
        self.id_to_message = dict(CATALOGS[normalize_language(locale_str)])

    @classmethod
    def get_bundle(cls, locale_str=None):
        if locale_str is None:
            from labelimg.i18n import system_language
            locale_str = system_language()
        return StringBundle(cls.__create_key, locale_str)

    def get_string(self, string_id):
        assert(string_id in self.id_to_message), "Missing string id : " + string_id
        return self.id_to_message[string_id]
