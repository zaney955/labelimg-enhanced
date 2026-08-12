"""Small geometry primitives shared by Canvas and Shape."""

from math import sqrt


def distance(point):
    return sqrt(point.x() * point.x() + point.y() * point.y())
