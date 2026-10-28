import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPOSITORY_ROOT / "tools" / "run_tests.py"
SPEC = importlib.util.spec_from_file_location("labelimg_test_runner", RUNNER_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


class RunTestsContractTest(unittest.TestCase):
    def test_partition_is_complete_stable_and_non_overlapping(self):
        files = [Path(f"test_{index}.py") for index in range(11)]

        shards = [
            RUNNER.partition_test_files(files, index, 4)
            for index in range(4)
        ]

        self.assertEqual([path for shard in shards for path in shard], [
            files[index]
            for shard_index in range(4)
            for index in range(shard_index, len(files), 4)
        ])
        self.assertEqual(set().union(*(set(shard) for shard in shards)), set(files))
        for left_index, left in enumerate(shards):
            for right in shards[left_index + 1:]:
                self.assertFalse(set(left) & set(right))

    def test_test_file_process_is_verbose_and_has_a_timeout(self):
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.object(
            RUNNER.subprocess, "run", return_value=completed,
        ) as run:
            return_code, failure = RUNNER.run_test_file(
                Path("tests/example/test_sample.py"),
                Path("tests"),
                {"PYTHONPATH": "src"},
                timeout_seconds=17,
            )

        self.assertEqual(return_code, 0)
        self.assertIsNone(failure)
        command = run.call_args.args[0]
        self.assertIn("-v", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 17)

    def test_timeout_becomes_an_explicit_file_failure(self):
        with mock.patch.object(
            RUNNER.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["python"], 23),
        ):
            return_code, failure = RUNNER.run_test_file(
                Path("tests/example/test_sample.py"),
                Path("tests"),
                {},
                timeout_seconds=23,
            )

        self.assertIsNone(return_code)
        self.assertEqual(failure, "timed out after 23 seconds")


if __name__ == "__main__":
    unittest.main()
