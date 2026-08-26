from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from MayaScope.model import BisectCandidate, BisectPlan
from MayaScope.runner import IsolatedMayaProbe, RunnerError, sha256_file


class IsolatedRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.ma"
        self.source.write_text("// isolated source", encoding="utf-8")
        self.plan = BisectPlan(
            source_scene=str(self.source),
            source_sha256=sha256_file(self.source),
            candidates=(
                BisectCandidate(
                    "asset",
                    "asset_GRP",
                    "top-level-dag",
                    metadata={"maya_names": ("asset_GRP",)},
                ),
            ),
            maya_executable=sys.executable,
            timeout_seconds=2,
            plan_id="runner-unit",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_success_result_is_read_from_owned_attempt(self):
        probe = IsolatedMayaProbe(self.plan, root=self.root / "runner")

        def fake_run(command, **kwargs):
            request_path = Path(command[-1])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            Path(request["progress_path"]).write_text(
                json.dumps({"stage": "exit"}), encoding="utf-8"
            )
            Path(request["result_path"]).write_text(
                json.dumps(
                    {
                        "outcome": "pass",
                        "stage": "exit",
                        "environment": {
                            "maya_version": "2025",
                            "loaded_plugins": ["matrixNodes"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(kwargs["shell"], False)
            self.assertEqual(kwargs["env"]["QT_QPA_PLATFORM"], "offscreen")
            return SimpleNamespace(returncode=0, stdout="probe ok", stderr="")

        with mock.patch("MayaScope.runner.isolated.subprocess.run", side_effect=fake_run):
            attempt = probe.run(("asset",), 0)
        self.assertEqual(attempt.outcome, "pass")
        self.assertEqual(attempt.stage, "exit")
        self.assertEqual(attempt.environment["maya_version"], "2025")
        self.assertEqual(attempt.environment["loaded_plugins"], ("matrixNodes",))
        self.assertTrue(Path(attempt.work_copy).is_file())
        self.assertEqual(sha256_file(self.source), self.plan.source_sha256)

    def test_timeout_is_a_failing_probe_with_last_known_stage(self):
        probe = IsolatedMayaProbe(self.plan, root=self.root / "timeout-runner")

        def timeout(command, **kwargs):
            request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
            Path(request["progress_path"]).write_text(
                json.dumps({"stage": "evaluate"}), encoding="utf-8"
            )
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with mock.patch("MayaScope.runner.isolated.subprocess.run", side_effect=timeout):
            attempt = probe.run(("asset",), 0)
        self.assertTrue(attempt.timed_out)
        self.assertEqual(attempt.outcome, "fail")
        self.assertEqual(attempt.stage, "evaluate")

    def test_changed_source_is_refused_before_copy_or_process(self):
        self.source.write_text("// changed after preview", encoding="utf-8")
        probe = IsolatedMayaProbe(self.plan, root=self.root / "changed-runner")
        with mock.patch("MayaScope.runner.isolated.subprocess.run") as process:
            with self.assertRaisesRegex(RunnerError, "checksum changed"):
                probe.run(("asset",), 0)
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
