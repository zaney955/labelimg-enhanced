"""Built-in image processing tools and recoverable commit support.

Submodules are imported explicitly so ordinary LabelImg startup does not load
the comparatively large OpenCV runtime before an image tool is requested.
"""
