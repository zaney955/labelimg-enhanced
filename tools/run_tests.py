"""Run each Qt test module in an isolated Python process."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument(
        "--installed",
        action="store_true",
        help="test the installed wheel instead of the repository source tree",
    )
    arguments = argument_parser.parse_args()

    repository_root = Path(__file__).resolve().parents[1]
    test_files = sorted((repository_root / "tests").glob("test_*.py"))
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    test_config_dir = Path(environment.get(
        "LABELIMG_CONFIG_DIR",
        repository_root / ".test-state" / "test-config",
    ))
    test_config_dir.mkdir(parents=True, exist_ok=True)
    environment["LABELIMG_CONFIG_DIR"] = str(test_config_dir)
    if arguments.installed:
        environment.pop("PYTHONPATH", None)
    else:
        environment["PYTHONPATH"] = str(repository_root / "src")

    failed = []
    for test_file in test_files:
        print(f"RUN {test_file.name}", flush=True)
        result = subprocess.run(
            [sys.executable, "-B", str(test_file)],
            cwd=repository_root,
            env=environment,
            check=False,
        )
        if result.returncode:
            failed.append(test_file.name)

    if failed:
        print("FAILED_FILES=" + ",".join(failed))
        return 1

    print(f"ALL_TEST_FILES_PASSED ({len(test_files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
