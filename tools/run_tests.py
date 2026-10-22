"""Run each Qt test module in an isolated Python process."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    target = argument_parser.add_mutually_exclusive_group()
    target.add_argument(
        "--installed",
        action="store_true",
        help="test the installed wheel instead of the repository source tree",
    )
    target.add_argument(
        "--package-root", type=Path,
        help="test an isolated wheel installation containing the labelimg package",
    )
    arguments = argument_parser.parse_args()

    repository_root = Path(__file__).resolve().parents[1]
    test_files = sorted((repository_root / "tests").rglob("test_*.py"))
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    test_config_dir = Path(environment.get(
        "LABELIMG_CONFIG_DIR",
        repository_root / ".test-state" / "test-config",
    ))
    test_config_dir.mkdir(parents=True, exist_ok=True)
    environment["LABELIMG_CONFIG_DIR"] = str(test_config_dir)
    if arguments.package_root:
        package_root = arguments.package_root.resolve()
        if not (package_root / "labelimg" / "__init__.py").is_file():
            argument_parser.error("--package-root must contain an installed labelimg package")
        environment["PYTHONPATH"] = str(package_root)
    elif arguments.installed:
        environment.pop("PYTHONPATH", None)
    else:
        environment["PYTHONPATH"] = str(repository_root / "src")

    failed = []
    for test_file in test_files:
        relative_test_file = test_file.relative_to(repository_root / "tests")
        print(f"RUN {relative_test_file}", flush=True)
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "faulthandler",
                "-B",
                "-m", "unittest", "discover",
                "-s", str(test_file.parent), "-p", test_file.name,
            ],
            cwd=repository_root,
            env=environment,
            check=False,
        )
        if result.returncode:
            print(
                "TEST_PROCESS_FAILED "
                f"{relative_test_file} exit_code={result.returncode}",
                flush=True,
            )
            failed.append(str(relative_test_file))

    if failed:
        print("FAILED_FILES=" + ",".join(failed))
        return 1

    print(f"ALL_TEST_FILES_PASSED ({len(test_files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
