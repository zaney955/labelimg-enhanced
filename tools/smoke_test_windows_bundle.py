"""Verify that the frozen Windows entry can import the complete workbench."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def smoke_test(executable, timeout=20, update_check=False):
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    environment = os.environ.copy()
    result_path = None
    if update_check:
        descriptor, result_path = tempfile.mkstemp(
            prefix="labelimg-update-smoke-",
            suffix=".txt",
        )
        os.close(descriptor)
        environment["LABELIMG_PACKAGING_UPDATE_SMOKE_RESULT"] = result_path
    else:
        environment["LABELIMG_PACKAGING_SMOKE_TEST"] = "1"
    process = subprocess.Popen([str(executable)], env=environment)
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if result_path is not None:
            Path(result_path).unlink(missing_ok=True)
        raise RuntimeError(
            "frozen workbench import did not finish within %s seconds" % timeout
        ) from error
    detail = ""
    if result_path is not None:
        try:
            detail = Path(result_path).read_text(encoding="utf-8")
        finally:
            Path(result_path).unlink(missing_ok=True)
    if return_code != 0:
        raise RuntimeError(
            "frozen check exited with code %s: %s"
            % (return_code, detail or "no detail")
        )
    return detail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--update-check", action="store_true")
    arguments = parser.parse_args()
    try:
        detail = smoke_test(
            arguments.executable,
            arguments.timeout,
            arguments.update_check,
        )
    except (OSError, RuntimeError) as error:
        print("Windows bundle smoke test failed: %s" % error, file=sys.stderr)
        return 1
    if arguments.update_check:
        print("Windows bundle update check succeeded: %s" % detail)
    else:
        print("Windows bundle imported the complete workbench successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
