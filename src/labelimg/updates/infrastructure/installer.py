"""Release-asset identity and integrity checks for Windows installers."""

from hashlib import sha256
from pathlib import Path
import re

from labelimg.updates.domain import StableVersion


MAX_SHA256_MANIFEST_BYTES = 128 * 1024
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
_SHA256_LINE = re.compile(
    r"^(?P<digest>[0-9a-fA-F]{64}) [ *](?P<name>[^\\/\r\n]+)$"
)


def installer_asset_name(version):
    version = StableVersion.parse(version)
    return "LabelImg-Enhanced-%s-windows-x64-setup.exe" % version


def parse_sha256_manifest(value, expected_name):
    expected_name = str(expected_name)
    matches = []
    for line in str(value).splitlines():
        match = _SHA256_LINE.fullmatch(line.strip())
        if match is not None and match.group("name") == expected_name:
            matches.append(match.group("digest").lower())
    if len(matches) != 1:
        raise ValueError("SHA256SUMS must contain exactly one installer entry")
    return matches[0]


def sha256_matches(path, expected_digest):
    expected_digest = str(expected_digest).strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
        return False
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected_digest
