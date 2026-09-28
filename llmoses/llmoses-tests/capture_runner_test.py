"""Regressions for bounded, persist-first smoke-runner capture."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).with_name("run_capture.sh")
PROGRESS = r"strategy-state|Generation|FinalResult|PASS|FAIL|error"


class CaptureRunner(unittest.TestCase):
    def invoke(self, producer, trace="summary", limit=5, heartbeat="30"):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "native.log"
            run = root / "run"
            run.mkdir()
            script = root / "producer.sh"
            script.write_text("#!/usr/bin/env bash\nset -eu\n" + producer)
            script.chmod(0o755)
            env = dict(os.environ, LLMOSES_HEARTBEAT_S=heartbeat)
            result = subprocess.run(
                [
                    "bash", "-c",
                    'source "$1"; shift; llmoses_capture_run "$@"',
                    "capture-test", str(HELPER), str(log), str(root),
                    "test-run", str(run), trace, str(limit), PROGRESS,
                    "--", str(script), str(log),
                ],
                text=True, capture_output=True, env=env, timeout=15,
            )
            return result, log.read_text()

    def test_summary_persists_complete_trace_but_bounds_terminal_output(self):
        producer = """
test -f "$1"
i=1
while [ "$i" -le 2000 ]; do
  printf 'noise-%04d\\n' "$i"
  i=$((i + 1))
done
echo '(strategy-state deep-lineage 5)'
"""
        result, log = self.invoke(producer)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(log.splitlines()), 2001)
        self.assertIn("noise-0001", log)
        self.assertIn("noise-2000", log)
        self.assertIn("(strategy-state deep-lineage 5)", result.stdout)
        self.assertLessEqual(len(result.stdout.splitlines()), 15)

    def test_full_mode_is_still_bounded_and_retains_full_log(self):
        producer = "i=1; while [ \"$i\" -le 100 ]; do echo line-$i; i=$((i + 1)); done\n"
        result, log = self.invoke(producer, trace="full", limit=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(log.splitlines()), 100)
        self.assertIn("middle lines omitted from terminal", result.stdout)
        self.assertLessEqual(len(result.stdout.splitlines()), 10)

    def test_child_exit_status_is_preserved(self):
        result, log = self.invoke("echo before-failure\nexit 7\n")
        self.assertEqual(result.returncode, 7)
        self.assertIn("before-failure", log)

    def test_heartbeat_exposes_progress_before_completion(self):
        producer = "echo '(Generation 1)'\nsleep 2\necho '(FinalResult ((ok 1.0)))'\n"
        result, log = self.invoke(producer, heartbeat="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[PeTTa progress]", result.stdout)
        self.assertIn("latest=(Generation 1)", result.stdout)
        self.assertIn("(FinalResult ((ok 1.0)))", log)


if __name__ == "__main__":
    unittest.main()
