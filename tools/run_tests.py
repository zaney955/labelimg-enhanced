"""Run each Qt test module in an isolated Python process."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


DEFAULT_TIMEOUT_SECONDS = 900


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def partition_test_files(test_files, shard_index, shard_count):
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be within shard_count")
    return list(test_files[shard_index::shard_count])


def run_test_file(
    test_file: Path,
    working_directory: Path,
    environment: dict[str, str],
    timeout_seconds: int,
):
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "faulthandler",
                "-B",
                "-m", "unittest", "discover",
                "-v",
                "-s", str(test_file.parent), "-p", test_file.name,
            ],
            cwd=working_directory,
            env=environment,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout_seconds} seconds"
    return result.returncode, None


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
    argument_parser.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="zero-based shard to run (default: 0)",
    )
    argument_parser.add_argument(
        "--shard-count",
        type=positive_integer,
        default=1,
        help="number of stable test-file shards (default: 1)",
    )
    argument_parser.add_argument(
        "--timeout-seconds",
        type=positive_integer,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "maximum runtime for one test file "
            f"(default: {DEFAULT_TIMEOUT_SECONDS})"
        ),
    )
    arguments = argument_parser.parse_args()
    if not 0 <= arguments.shard_index < arguments.shard_count:
        argument_parser.error("--shard-index must be within --shard-count")

    repository_root = Path(__file__).resolve().parents[1]
    tests_root = repository_root / "tests"
    all_test_files = sorted(tests_root.rglob("test_*.py"))
    test_files = partition_test_files(
        all_test_files, arguments.shard_index, arguments.shard_count,
    )
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

    print(
        "TEST_SHARD "
        f"{arguments.shard_index + 1}/{arguments.shard_count} "
        f"({len(test_files)} of {len(all_test_files)} files)",
        flush=True,
    )
    failed = []
    for test_file in test_files:
        relative_test_file = test_file.relative_to(tests_root)
        print(f"RUN {relative_test_file}", flush=True)
        return_code, failure = run_test_file(
            test_file,
            repository_root,
            environment,
            timeout_seconds=arguments.timeout_seconds,
        )
        if failure is not None:
            print(f"TEST_PROCESS_TIMEOUT {relative_test_file} {failure}", flush=True)
            failed.append(f"{relative_test_file} ({failure})")
        elif return_code:
            print(
                "TEST_PROCESS_FAILED "
                f"{relative_test_file} exit_code={return_code}",
                flush=True,
            )
            failed.append(f"{relative_test_file} (exit code {return_code})")

    if failed:
        print("FAILED_FILES=" + ",".join(failed))
        return 1

    print(f"ALL_TEST_FILES_PASSED ({len(test_files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
