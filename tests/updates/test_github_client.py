import unittest

from PyQt5.QtCore import QCoreApplication, QIODevice, QUrl
from PyQt5.QtNetwork import QNetworkReply, QNetworkRequest

from labelimg.updates import (
    GITHUB_LATEST_RELEASE_WEB_URL,
    GitHubReleaseClient,
)


class FakeReply(QNetworkReply):
    def __init__(
        self,
        url,
        *,
        status,
        body=b"",
        error=QNetworkReply.NoError,
        error_text="",
        redirect_target=None,
        parent=None,
    ):
        super().__init__(parent)
        self._body = bytes(body)
        self._offset = 0
        self.setUrl(QUrl(url))
        self.setAttribute(QNetworkRequest.HttpStatusCodeAttribute, status)
        if redirect_target is not None:
            self.setAttribute(
                QNetworkRequest.RedirectionTargetAttribute,
                QUrl(redirect_target),
            )
        if error != QNetworkReply.NoError:
            self.setError(error, error_text)
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
        self.requests.append(("GET", request))
        return self.replies.pop(0)

    def head(self, request):
        raise AssertionError("HEAD reproduces the user's closed connection")


class GitHubReleaseClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_check_uses_public_latest_get_without_api_or_head(self):
        web_reply = FakeReply(
            GITHUB_LATEST_RELEASE_WEB_URL,
            status=302,
            redirect_target=(
                "https://github.com/zaney955/labelimg-enhanced/"
                "releases/tag/v2.2.0"
            ),
        )
        manager = FakeManager((web_reply,))
        client = GitHubReleaseClient("2.1.0", manager=manager)
        releases = []
        failures = []
        client.succeeded.connect(
            releases.append
        )
        client.failed.connect(failures.append)

        self.assertTrue(client.fetch())
        web_reply.finished.emit()

        self.assertEqual(
            [
                (method, request.url().toString())
                for method, request in manager.requests
            ],
            [("GET", GITHUB_LATEST_RELEASE_WEB_URL)],
        )
        self.assertEqual([str(item.version) for item in releases], ["2.2.0"])
        self.assertEqual(failures, [])

    def test_retries_when_github_closes_the_connection(self):
        closed_reply = FakeReply(
            GITHUB_LATEST_RELEASE_WEB_URL,
            status=0,
            error=QNetworkReply.RemoteHostClosedError,
            error_text="Connection closed",
        )
        recovered_reply = FakeReply(
            GITHUB_LATEST_RELEASE_WEB_URL,
            status=302,
            redirect_target=(
                "https://github.com/zaney955/labelimg-enhanced/"
                "releases/tag/v2.2.0"
            ),
        )
        manager = FakeManager((closed_reply, recovered_reply))
        client = GitHubReleaseClient(
            "2.1.0",
            manager=manager,
            retry_delays_ms=(0,),
        )
        releases = []
        failures = []
        client.succeeded.connect(releases.append)
        client.failed.connect(failures.append)

        self.assertTrue(client.fetch())
        closed_reply.finished.emit()
        self.application.processEvents()
        recovered_reply.finished.emit()

        self.assertEqual(len(manager.requests), 2)
        self.assertEqual([str(item.version) for item in releases], ["2.2.0"])
        self.assertEqual(failures, [])

    def test_reports_connection_closed_after_retry_budget_is_exhausted(self):
        replies = [
            FakeReply(
                GITHUB_LATEST_RELEASE_WEB_URL,
                status=0,
                error=QNetworkReply.RemoteHostClosedError,
                error_text="Connection closed",
            )
            for _ in range(3)
        ]
        manager = FakeManager(replies)
        client = GitHubReleaseClient(
            "2.1.0",
            manager=manager,
            retry_delays_ms=(0, 0),
        )
        failures = []
        client.failed.connect(failures.append)

        self.assertTrue(client.fetch())
        for reply in replies:
            reply.finished.emit()
            self.application.processEvents()

        self.assertEqual(len(manager.requests), 3)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0])

    def test_cancel_stops_a_pending_retry(self):
        closed_reply = FakeReply(
            GITHUB_LATEST_RELEASE_WEB_URL,
            status=0,
            error=QNetworkReply.RemoteHostClosedError,
            error_text="Connection closed",
        )
        unused_reply = FakeReply(
            GITHUB_LATEST_RELEASE_WEB_URL,
            status=302,
            redirect_target=(
                "https://github.com/zaney955/labelimg-enhanced/"
                "releases/tag/v2.2.0"
            ),
        )
        manager = FakeManager((closed_reply, unused_reply))
        client = GitHubReleaseClient(
            "2.1.0",
            manager=manager,
            retry_delays_ms=(10000,),
        )

        self.assertTrue(client.fetch())
        closed_reply.finished.emit()
        client.cancel()
        self.application.processEvents()

        self.assertEqual(len(manager.requests), 1)


if __name__ == "__main__":
    unittest.main()
