import unittest

from labelimg.updates import (
    GITHUB_LATEST_RELEASE_WEB_URL,
    build_web_request_headers,
    installer_asset_name,
    release_from_latest_redirect,
)


class GitHubReleaseParserTest(unittest.TestCase):
    def test_builds_stable_release_from_latest_web_redirect(self):
        release = release_from_latest_redirect(
            "https://github.com/zaney955/labelimg-enhanced/"
            "releases/tag/v2.2.0"
        )

        self.assertEqual(
            GITHUB_LATEST_RELEASE_WEB_URL,
            "https://github.com/zaney955/labelimg-enhanced/releases/latest",
        )
        self.assertEqual(str(release.version), "2.2.0")
        self.assertEqual(release.summary, "")
        self.assertTrue(
            release.wheel_url.endswith(
                "/labelimg_enhanced-2.2.0-py3-none-any.whl"
            )
        )
        self.assertTrue(release.installer_url.endswith(
            "/%s" % installer_asset_name("2.2.0")
        ))
        self.assertTrue(release.sha256_url.endswith("/SHA256SUMS"))

    def test_rejects_unstable_or_foreign_latest_web_redirects(self):
        urls = (
            "https://github.com/zaney955/labelimg-enhanced/releases/tag/v2.2.0rc1",
            "https://github.com/other/project/releases/tag/v2.2.0",
            "https://example.invalid/zaney955/labelimg-enhanced/releases/tag/v2.2.0",
        )
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    release_from_latest_redirect(url)

    def test_web_request_headers_are_public_and_identify_the_app(self):
        headers = build_web_request_headers("2.1.0")

        self.assertEqual(headers["Accept"], "text/html")
        self.assertIn("LabelImg-Enhanced/2.1.0", headers["User-Agent"])
        self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
