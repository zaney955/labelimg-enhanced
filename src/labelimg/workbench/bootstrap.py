"""Compose and launch the LabelImg Enhanced workbench."""

import argparse
from dataclasses import dataclass
import os
import sys

from PyQt5.QtWidgets import QApplication

from labelimg.ui.actions import new_icon
from labelimg.workbench.composition import WorkbenchComposer
from labelimg.workbench.main_window import MainWindow
from labelimg.workbench.support import APP_NAME


@dataclass(frozen=True)
class WorkbenchLaunchOptions:
    image_dir: str | None = None
    class_file: str | None = None
    save_dir: str | None = None


def parse_launch_options(argv=()):
    """Translate the legacy positional CLI into an immutable launch request."""
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir", nargs="?")
    parser.add_argument(
        "class_file",
        default=os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data",
            "predefined_classes.txt",
        ),
        nargs="?",
    )
    parser.add_argument("save_dir", nargs="?")
    args = parser.parse_args(list(argv)[1:])
    return WorkbenchLaunchOptions(
        *(
            os.path.normpath(value) if value else None
            for value in (args.image_dir, args.class_file, args.save_dir)
        )
    )


def create_workbench(
    options,
    *,
    window_factory=MainWindow,
    composer=WorkbenchComposer.compose,
):
    """Construct the concrete window from feature-neutral launch options."""
    if not isinstance(options, WorkbenchLaunchOptions):
        raise TypeError("create_workbench requires WorkbenchLaunchOptions")
    window = window_factory()
    composer(
        window,
        options.image_dir,
        options.class_file,
        options.save_dir,
    )
    return window


def get_main_app(argv=None):
    """Create the Qt application and its one concrete workbench window."""
    argv = [] if argv is None else list(argv)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(new_icon("app"))
    window = create_workbench(parse_launch_options(argv))
    window.show()
    return app, window


def main():
    app, _window = get_main_app(sys.argv)
    return app.exec_()


__all__ = (
    "WorkbenchLaunchOptions",
    "create_workbench",
    "get_main_app",
    "main",
    "parse_launch_options",
)
