"""Validation for GitHub's public latest stable Release redirect."""

from urllib.parse import urlsplit

from labelimg.updates.domain import StableRelease, StableVersion
from .installer import installer_asset_name


GITHUB_LATEST_RELEASE_WEB_URL = (
    "https://github.com/zaney955/labelimg-enhanced/releases/latest"
)
MAX_RELEASE_RESPONSE_BYTES = 1024 * 1024
_RELEASE_PATH_PREFIX = "/zaney955/labelimg-enhanced/releases/"


def build_web_request_headers(app_version):
    return {
        "Accept": "text/html",
        "User-Agent": "LabelImg-Enhanced/%s" % app_version,
    }


def release_from_latest_redirect(value):
    """Build minimal metadata from GitHub's latest stable web redirect."""
    url = str(value or "").strip()
    parsed = urlsplit(url)
    tag_prefix = _RELEASE_PATH_PREFIX + "tag/"
    if not parsed.path.startswith(tag_prefix):
        raise ValueError("latest release redirect has no project tag")
    tag_name = parsed.path[len(tag_prefix):]
    if not tag_name or "/" in tag_name:
        raise ValueError("latest release redirect has an invalid tag")
    version = StableVersion.parse(tag_name)
    if tag_name != "v%s" % version:
        raise ValueError("latest release redirect is not a stable tag")
    html_url = _validated_release_url(url, tag_name)
    return StableRelease(
        version=version,
        tag_name=tag_name,
        name="LabelImg Enhanced %s" % version,
        summary="",
        html_url=html_url,
        published_at="",
        wheel_url=_contract_wheel_url(tag_name, version),
        installer_url=_contract_installer_url(tag_name, version),
        sha256_url=_contract_asset_url(tag_name, "SHA256SUMS"),
    )


def _validated_release_url(value, tag_name):
    url = str(value or "").strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.path != _RELEASE_PATH_PREFIX + "tag/" + tag_name
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("release URL is outside the canonical repository")
    return url


def _contract_wheel_url(tag_name, version):
    return _contract_asset_url(
        tag_name,
        "labelimg_enhanced-%s-py3-none-any.whl" % version,
    )


def _contract_installer_url(tag_name, version):
    return _contract_asset_url(tag_name, installer_asset_name(version))


def _contract_asset_url(tag_name, asset_name):
    return (
        "https://github.com/zaney955/labelimg-enhanced/releases/download/"
        "%s/%s" % (tag_name, asset_name)
    )
