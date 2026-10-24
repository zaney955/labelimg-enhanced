"""Immutable update metadata and stable-version identities."""

from dataclasses import dataclass
from enum import Enum
import re


_STABLE_VERSION = re.compile(
    r"^v?(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)$"
)


@dataclass(frozen=True, order=True)
class StableVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value):
        match = _STABLE_VERSION.fullmatch(str(value or "").strip())
        if match is None:
            raise ValueError("expected a stable X.Y.Z version")
        return cls(*(int(match.group(name)) for name in (
            "major", "minor", "patch"
        )))

    def __str__(self):
        return "%d.%d.%d" % (self.major, self.minor, self.patch)


@dataclass(frozen=True)
class StableRelease:
    version: StableVersion
    tag_name: str
    name: str
    summary: str
    html_url: str
    published_at: str
    wheel_url: str | None = None
    installer_url: str | None = None
    sha256_url: str | None = None

    def to_mapping(self):
        return {
            "version": str(self.version),
            "tag_name": self.tag_name,
            "name": self.name,
            "summary": self.summary,
            "html_url": self.html_url,
            "published_at": self.published_at,
            "wheel_url": self.wheel_url,
            "installer_url": self.installer_url,
            "sha256_url": self.sha256_url,
        }


class UpdateDecisionKind(Enum):
    AVAILABLE = "available"
    UP_TO_DATE = "up-to-date"
    IGNORED = "ignored"
    SNOOZED = "snoozed"


@dataclass(frozen=True)
class UpdateDecision:
    kind: UpdateDecisionKind
    release: StableRelease
