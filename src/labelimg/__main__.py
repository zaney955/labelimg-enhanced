"""Run LabelImg Enhanced with ``python -m labelimg``."""

import os
from pathlib import Path

from labelimg.workbench.bootstrap import main


def _run_packaged_update_smoke_test(result_path):
    from PyQt5.QtCore import QCoreApplication, QTimer

    from labelimg import __version__
    from labelimg.updates.ui import GitHubReleaseClient

    application = QCoreApplication.instance() or QCoreApplication([])
    client = GitHubReleaseClient(__version__)

    def finish(code, detail):
        Path(result_path).write_text(str(detail), encoding="utf-8")
        application.exit(code)

    client.succeeded.connect(
        lambda release: finish(0, "success:%s" % release.tag_name)
    )
    client.failed.connect(lambda detail: finish(10, "failure:%s" % detail))
    QTimer.singleShot(15000, lambda: finish(11, "timeout"))
    client.fetch()
    return application.exec_()


if __name__ == '__main__':
    update_smoke_result = os.environ.get(
        "LABELIMG_PACKAGING_UPDATE_SMOKE_RESULT"
    )
    if update_smoke_result:
        raise SystemExit(_run_packaged_update_smoke_test(update_smoke_result))
    if os.environ.get("LABELIMG_PACKAGING_SMOKE_TEST") == "1":
        raise SystemExit(0)
    raise SystemExit(main())
