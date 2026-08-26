from hashlib import sha256
from pathlib import Path
import unittest

from PyQt5.QtCore import QCoreApplication, QIODevice, QUrl
from PyQt5.QtNetwork import QNetworkReply, QNetworkRequest

from labelimg.updates import (
    InstallerDownloadClient,
    StableRelease,
    StableVersion,
    installer_asset_name,
)


class FakeReply(QNetworkReply):
    def __init__(self, url, body, parent=None):
        super().__init__(parent)
        self._body = bytes(body)
        self._offset = 0
        self.setUrl(QUrl(url))
        self.setAttribute(QNetworkRequest.HttpStatusCodeAttribute, 200)
        self.open(QIODevice.ReadOnly | QIODevice.Unbuffered)

    def abort(self):
        pass

    def bytesAvailable(self):
        return len(self._body) - self._offset + super().bytesAvailable()

    def readData(self, maximum):
        if self._offset >= len(self._body):
            return bytes()
        chunk = self._body[self._offset:self._offset + maximum]
        self._offset += len(chunk)
        return chunk


class FakeManager:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def get(self, request):
        self.requests.append(request.url().toString())
        return self.replies.pop(0)


def release():
    version = StableVersion.parse("2.2.0")
    root = (
        "https://github.com/zaney955/labelimg-enhanced/"
        "releases/download/v2.2.0/"
    )
    return StableRelease(
        version=version,
        tag_name="v2.2.0",
        name="LabelImg Enhanced 2.2.0",
        summary="",
        html_url=root,
        published_at="",
        installer_url=root + installer_asset_name(version),
        sha256_url=root + "SHA256SUMS",
    )


class InstallerDownloadClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_downloads_manifest_then_installer_and_emits_verified_path(self):
        payload = b"unsigned installer"
        digest = sha256(payload).hexdigest()
        current_release = release()
        manifest = "%s *%s\n" % (
            digest,
            installer_asset_name(current_release.version),
        )
        manifest_reply = FakeReply(current_release.sha256_url, manifest.encode())
        installer_reply = FakeReply(current_release.installer_url, payload)
        manager = FakeManager((manifest_reply, installer_reply))
        client = InstallerDownloadClient("2.1.0", manager=manager)
        candidates = []
        failures = []
        client.succeeded.connect(candidates.append)
        client.failed.connect(failures.append)

        self.assertTrue(client.download(current_release))
        manifest_reply.readyRead.emit()
        manifest_reply.finished.emit()
        installer_reply.readyRead.emit()
        installer_reply.finished.emit()

        self.assertEqual(
            manager.requests,
            [current_release.sha256_url, current_release.installer_url],
        )
        self.assertEqual(failures, [])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(Path(candidates[0]).read_bytes(), payload)
        self.assertEqual(client.candidate_path, candidates[0])
        client.cancel()

    def test_hash_mismatch_never_emits_a_candidate(self):
        current_release = release()
        manifest = "%s *%s\n" % (
            "00" * 32,
            installer_asset_name(current_release.version),
        )
        manifest_reply = FakeReply(current_release.sha256_url, manifest.encode())
        installer_reply = FakeReply(current_release.installer_url, b"different")
        client = InstallerDownloadClient(
            "2.1.0",
            manager=FakeManager((manifest_reply, installer_reply)),
        )
        candidates = []
        failures = []
        client.succeeded.connect(candidates.append)
        client.failed.connect(failures.append)

        client.download(current_release)
        manifest_reply.readyRead.emit()
        manifest_reply.finished.emit()
        installer_reply.readyRead.emit()
        installer_reply.finished.emit()

        self.assertEqual(candidates, [])
        self.assertEqual(len(failures), 1)


if __name__ == "__main__":
    unittest.main()
