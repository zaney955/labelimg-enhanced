import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from labelimg.updates import (
    DistributionStrategy,
    detect_distribution_strategy,
)


class DistributionStrategyTest(unittest.TestCase):
    def test_python_process_is_not_self_managed(self):
        self.assertIs(
            detect_distribution_strategy(
                frozen=False,
                executable=sys.executable,
                platform_name="win32",
            ),
            DistributionStrategy.PYTHON,
        )

    def test_frozen_build_without_installer_marker_is_portable(self):
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "LabelImgEnhanced.exe"

            strategy = detect_distribution_strategy(
                frozen=True,
                executable=executable,
                platform_name="win32",
            )

        self.assertIs(strategy, DistributionStrategy.PORTABLE_FROZEN)

    def test_inno_marker_distinguishes_a_managed_windows_install(self):
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "LabelImgEnhanced.exe"
            executable.parent.joinpath("managed-install.json").write_text(
                '{"installer":"inno","scope":"current-user"}',
                encoding="utf-8",
            )

            strategy = detect_distribution_strategy(
                frozen=True,
                executable=executable,
                platform_name="win32",
            )

        self.assertIs(strategy, DistributionStrategy.MANAGED_WINDOWS)


if __name__ == "__main__":
    unittest.main()
