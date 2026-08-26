from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock

from MayaScope.audit import _atomic_json, run_audit, verify_audit_report


class AuditTests(unittest.TestCase):
    def test_parent_launches_hidden_worker_and_returns_machine_report(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder) / "shot.ma"
            scene.write_text("//Maya ASCII 2025 scene\n", encoding="utf-8")

            def fake_run(command, **kwargs):
                request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
                Path(request["result_path"]).write_text(
                    json.dumps(
                        {
                            "format": "mayascope.clinic-audit",
                            "schema_version": 1,
                            "ok": True,
                            "gate_failed": True,
                            "issues": [{"severity": "error"}],
                        }
                    ),
                    encoding="utf-8",
                )
                self.assertFalse(kwargs["shell"])
                self.assertEqual(kwargs["env"]["QT_QPA_PLATFORM"], "offscreen")
                self.assertIn("MayaScope.audit_worker", command)
                return SimpleNamespace(returncode=2, stdout="", stderr="")

            with mock.patch("MayaScope.audit.locate_mayapy", return_value=Path(sys.executable)):
                with mock.patch("MayaScope.audit.subprocess.run", side_effect=fake_run):
                    result = run_audit(scene, profile="publish", fail_on="error")
            self.assertTrue(result["ok"])
            self.assertTrue(result["gate_failed"])
            self.assertEqual(result["worker_exit_code"], 2)

    def test_performance_request_is_forwarded_to_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder) / "shot.ma"
            scene.write_text("//Maya ASCII 2025 scene\n", encoding="utf-8")

            def fake_run(command, **kwargs):
                request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
                self.assertEqual(request["performance_samples"], 9)
                self.assertEqual(request["performance_warmups"], 3)
                Path(request["result_path"]).write_text(
                    json.dumps({"ok": True, "gate_failed": False}), encoding="utf-8"
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch("MayaScope.audit.locate_mayapy", return_value=Path(sys.executable)):
                with mock.patch("MayaScope.audit.subprocess.run", side_effect=fake_run):
                    result = run_audit(
                        scene, performance_samples=9, performance_warmups=3
                    )
            self.assertTrue(result["ok"])

    def test_explicit_workspace_is_validated_and_forwarded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = root / "shot.ma"
            workspace = root / "project"
            workspace.mkdir()
            scene.write_text("//Maya ASCII 2025 scene\n", encoding="utf-8")

            def fake_run(command, **kwargs):
                request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
                self.assertEqual(Path(request["workspace"]), workspace.resolve())
                Path(request["result_path"]).write_text(
                    json.dumps({"ok": True, "gate_failed": False}), encoding="utf-8"
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with mock.patch("MayaScope.audit.locate_mayapy", return_value=Path(sys.executable)):
                with mock.patch("MayaScope.audit.subprocess.run", side_effect=fake_run):
                    result = run_audit(scene, workspace=workspace)
            self.assertTrue(result["ok"])
            with self.assertRaisesRegex(ValueError, "workspace"):
                run_audit(scene, workspace=root / "missing")

    def test_scene_extension_is_fail_closed_before_process(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder) / "shot.txt"
            scene.write_text("not maya", encoding="utf-8")
            with mock.patch("MayaScope.audit.subprocess.run") as process:
                with self.assertRaisesRegex(ValueError, "requires an existing"):
                    run_audit(scene)
            process.assert_not_called()

    def test_report_checksum_verifies_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "audit.json"
            _atomic_json(
                report,
                {
                    "format": "mayascope.clinic-audit",
                    "schema_version": 1,
                    "ok": True,
                    "gate_failed": False,
                    "issues": [],
                },
            )
            verified = verify_audit_report(report)
            self.assertTrue(verified["ok"])
            self.assertEqual(verified["schema_version"], 2)
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["gate_failed"] = True
            report.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify_audit_report(report)

    def test_worker_exit_must_match_report_state(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder) / "shot.ma"
            scene.write_text("//Maya ASCII 2025 scene\n", encoding="utf-8")

            def fake_run(command, **kwargs):
                request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
                Path(request["result_path"]).write_text(
                    json.dumps({"ok": True, "gate_failed": False}), encoding="utf-8"
                )
                return SimpleNamespace(returncode=2, stdout="", stderr="")

            with mock.patch("MayaScope.audit.locate_mayapy", return_value=Path(sys.executable)):
                with mock.patch("MayaScope.audit.subprocess.run", side_effect=fake_run):
                    with self.assertRaisesRegex(RuntimeError, "exit/report mismatch"):
                        run_audit(scene)

    def test_queue_lifecycle_uses_managed_child_and_reports_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = Path(folder) / "shot.ma"
            scene.write_text("//Maya ASCII 2025 scene\n", encoding="utf-8")
            started, finished = [], []

            class FakeProcess:
                pid = 24680
                returncode = None
                _handle = 1

                def __init__(self, command, **kwargs):
                    request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
                    Path(request["result_path"]).write_text(
                        json.dumps({"ok": True, "gate_failed": False}), encoding="utf-8"
                    )

                def communicate(self, timeout=None):
                    self.returncode = 0
                    return "", ""

                def poll(self):
                    return self.returncode

                def kill(self):
                    self.returncode = 1

            identity = SimpleNamespace(to_dict=lambda: {
                "pid": 24680, "executable": "mayapy.exe", "started_ticks": 12
            })
            guard = SimpleNamespace(assigned=True, close=mock.Mock())
            with mock.patch("MayaScope.audit.locate_mayapy", return_value=Path(sys.executable)):
                with mock.patch("MayaScope.audit.subprocess.Popen", side_effect=FakeProcess):
                    with mock.patch("MayaScope.process_guard.ChildJobGuard", return_value=guard):
                        with mock.patch("MayaScope.process_guard.get_process_identity", return_value=identity):
                            result = run_audit(
                                scene,
                                process_started=started.append,
                                process_finished=finished.append,
                            )
            self.assertTrue(result["ok"])
            self.assertEqual(started[0]["pid"], 24680)
            self.assertTrue(started[0]["job_kill_on_close"])
            self.assertEqual(finished[0]["returncode"], 0)
            guard.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
