"""Validate the immutable version contract for a tagged release."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

from labelimg import __version__


STABLE_TAG = re.compile(r"^v([0-9]+\.[0-9]+\.[0-9]+)$")


def validate(
    tag: str,
    wheels: list[Path],
    installers: list[Path],
) -> list[str]:
    errors: list[str] = []
    match = STABLE_TAG.fullmatch(tag)
    expected_tag = "v%s" % __version__
    if match is None:
        errors.append("release tag must use the stable form vMAJOR.MINOR.PATCH")
    elif tag != expected_tag:
        errors.append(
            "release tag %s does not match application version %s"
            % (tag, __version__)
        )

    expected_wheel = (
        "labelimg_enhanced-%s-py3-none-any.whl" % __version__
    )
    for wheel in wheels:
        if wheel.name != expected_wheel:
            errors.append(
                "wheel %s does not match expected artifact %s"
                % (wheel.name, expected_wheel)
            )
        if not wheel.is_file():
            errors.append("wheel does not exist: %s" % wheel)
    expected_installer = (
        "LabelImg-Enhanced-%s-windows-x64-setup.exe" % __version__
    )
    for installer in installers:
        if installer.name != expected_installer:
            errors.append(
                "installer %s does not match expected artifact %s"
                % (installer.name, expected_installer)
            )
        if not installer.is_file():
            errors.append("installer does not exist: %s" % installer)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--wheel", action="append", default=[])
    parser.add_argument("--installer", action="append", default=[])
    arguments = parser.parse_args()
    errors = validate(
        arguments.tag,
        [Path(value) for value in arguments.wheel],
        [Path(value) for value in arguments.installer],
    )
    if errors:
        for error in errors:
            print("release validation failed: %s" % error, file=sys.stderr)
        return 1
    print(
        "release contract valid for %s (%s)"
        % (arguments.tag, __version__)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
