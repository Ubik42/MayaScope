from __future__ import annotations

import json
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from MayaScope.project_audit import verify_project_audit
from MayaScope.project_queue import (
    InsufficientStorageError,
    QueueBusyError,
    QueueLease,
    _atomic_signed,
    create_project_plan,
    main,
    run_project_plan,
    verify_project_plan,
    verify_queue_journal,
    preflight_storage,
)
from MayaScope.process_guard import ProcessIdentity


def worker_report(scene: Path, gate_failed=False):
    return {
        "format": "mayascope.clinic-audit",
        "schema_version": 2,
        "ok": True,
        "gate_failed": gate_failed,
        "worker_exit_code": 2 if gate_failed else 0,
        "source_scene": str(scene.resolve()),
        "source_sha256": "ignored-by-queue-writer",
        "profile": "publish",
        "config_fingerprint": "team-a",
        "maya": {"version": "2025", "api": 20250303},
        "snapshot": {"scene_lifecycle": {"workspace_root": "D:/show"}},
        "issues": (
            [{
                "rule_id": "scene-contract", "severity": "error",
                "atomic_subjects": [{"id": "scene-contract:time", "node_id": ""}],
            }]
            if gate_failed else []
        ),
    }


class ProjectQueueTests(unittest.TestCase):
    def _scenes(self, root):
        scenes = (root / "shot010.ma", root / "shot020.ma")
        for scene in scenes:
            scene.write_text("// Maya ASCII 2025\n%s" % scene.stem, encoding="utf-8")
        return scenes

    def test_plan_is_deterministic_signed_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenes = self._scenes(root)
            plan_path = root / "plan.json"
            first = create_project_plan(reversed(scenes), plan_path)
            second = create_project_plan(scenes)
            self.assertEqual(first["plan_sha256"], second["plan_sha256"])
            self.assertEqual(verify_project_plan(plan_path)["plan_sha256"], first["plan_sha256"])
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["settings"]["profile"] = "all"
            plan_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "签名不匹配"):
                verify_project_plan(plan_path)

    def test_pause_then_resume_reuses_completed_report_and_builds_project_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenes = self._scenes(root)
            plan_path, journal_path = root / "plan.json", root / "journal.json"
            reports, bundle = root / "reports", root / "project.json"
            create_project_plan(scenes, plan_path)
            calls = []

            def audit(scene, **_kwargs):
                calls.append(Path(scene).name)
                return worker_report(Path(scene), gate_failed=Path(scene).stem == "shot020")

            with mock.patch("MayaScope.project_queue.run_audit", side_effect=audit):
                paused = run_project_plan(
                    plan_path, journal_path, reports, bundle, max_scenes=1
                )
                self.assertEqual(paused["state"], "已暂停")
                self.assertEqual(paused["summary"]["passed"], 1)
                completed = run_project_plan(plan_path, journal_path, reports, bundle)
            self.assertEqual(calls, ["shot010.ma", "shot020.ma"])
            self.assertEqual(completed["state"], "完成")
            self.assertEqual(completed["summary"]["blocked"], 1)
            self.assertEqual(completed["jobs"][0]["attempts"], 1)
            self.assertEqual(verify_queue_journal(journal_path, verify_project_plan(plan_path))["state"], "完成")
            self.assertEqual(verify_project_audit(bundle)["summary"]["scene_count"], 2)

    def test_stale_running_job_recovers_and_records_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenes = self._scenes(root)
            plan_path, journal_path = root / "plan.json", root / "journal.json"
            create_project_plan(scenes, plan_path)
            with mock.patch("MayaScope.project_queue.run_audit", return_value=worker_report(scenes[0])):
                run_project_plan(plan_path, journal_path, root / "reports", max_scenes=0)
            journal = verify_queue_journal(journal_path)
            journal["jobs"][0]["status"] = "运行中"
            journal["state"] = "运行中"
            _atomic_signed(journal_path, journal, "journal_sha256")
            with mock.patch("MayaScope.project_queue.run_audit", side_effect=lambda scene, **kwargs: worker_report(Path(scene))):
                completed = run_project_plan(plan_path, journal_path, root / "reports")
            self.assertEqual(completed["state"], "完成")
            self.assertEqual(completed["recovery_count"], 1)
            self.assertEqual(completed["jobs"][0]["attempts"], 1)

    def test_source_and_config_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = self._scenes(root)[0]
            config = root / "clinic.json"
            config.write_text("{}", encoding="utf-8")
            plan = root / "plan.json"
            create_project_plan((scene,), plan, config=config)
            config.write_text('{"changed": true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "配置.*变化"):
                run_project_plan(plan, root / "journal.json", root / "reports")

    def test_worker_failure_is_persisted_and_retryable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = self._scenes(root)[0]
            plan, journal = root / "plan.json", root / "journal.json"
            create_project_plan((scene,), plan)
            with mock.patch("MayaScope.project_queue.run_audit", side_effect=RuntimeError("host failed")):
                failed = run_project_plan(plan, journal, root / "reports")
            self.assertEqual(failed["state"], "需要重试")
            self.assertEqual(failed["jobs"][0]["status"], "失败")
            with mock.patch("MayaScope.project_queue.run_audit", return_value=worker_report(scene)):
                completed = run_project_plan(plan, journal, root / "reports")
            self.assertEqual(completed["state"], "完成")
            self.assertEqual(completed["jobs"][0]["attempts"], 2)

    def test_cli_create_run_and_verify_preserve_gate_exit_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = self._scenes(root)[0]
            plan, journal = root / "plan.json", root / "journal.json"
            reports, bundle = root / "reports", root / "project.json"
            stream = io.StringIO()
            with redirect_stdout(stream):
                self.assertEqual(main(["create", str(scene), "--plan", str(plan)]), 0)
                self.assertEqual(main(["verify", str(plan)]), 0)
                with mock.patch(
                    "MayaScope.project_queue.run_audit",
                    return_value=worker_report(scene, gate_failed=True),
                ):
                    self.assertEqual(
                        main([
                            "run", str(plan), "--journal", str(journal),
                            "--report-dir", str(reports), "--project-report", str(bundle),
                        ]),
                        2,
                    )
                self.assertEqual(main(["verify", str(journal), "--plan", str(plan)]), 0)
            rows = [json.loads(line) for line in stream.getvalue().splitlines()]
            self.assertEqual(rows[2]["state"], "完成")
            self.assertEqual(rows[2]["blocked"], 1)

    def test_kernel_lease_rejects_second_owner_and_preserves_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock = root / "queue.lock"
            journal = root / "queue.json"
            first = QueueLease(lock, "a" * 64, journal).acquire()
            try:
                with self.assertRaisesRegex(QueueBusyError, "当前进程持有"):
                    QueueLease(lock, "a" * 64, journal).acquire()
                self.assertEqual(first.metadata["token"], first.token)
            finally:
                first.release()
            receipt = json.loads(first.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["state"], "已释放")
            self.assertIsNone(receipt["worker"])

    def test_kernel_lease_blocks_a_second_process_and_exposes_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock, journal = root / "queue.lock", root / "queue.json"
            script = (
                "import sys; from pathlib import Path; "
                "from MayaScope.project_queue import QueueLease; "
                "lease=QueueLease(Path(sys.argv[1]),'a'*64,Path(sys.argv[2])).acquire(); "
                "print('ready',flush=True); sys.stdin.readline(); lease.release()"
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(lock), str(journal)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "ready")
                with self.assertRaisesRegex(QueueBusyError, "正由 PID") as caught:
                    QueueLease(lock, "a" * 64, journal).acquire()
                self.assertIn(str(child.pid), str(caught.exception))
            finally:
                child.stdin.write("\n")
                child.stdin.flush()
                child.wait(timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr.read())

    def test_storage_preflight_is_volume_aware_and_fails_before_maya(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = self._scenes(root)[0]
            plan = create_project_plan(
                (scene,), minimum_free_bytes=1000, estimated_report_bytes=500
            )
            usage = shutil._ntuple_diskusage(total=10000, used=9000, free=1000)
            with mock.patch("MayaScope.project_queue.shutil.disk_usage", return_value=usage):
                with self.assertRaises(InsufficientStorageError) as caught:
                    preflight_storage(
                        plan, root / "journal.json", root / "reports",
                        root / "project.json", 1,
                    )
            self.assertTrue(caught.exception.evidence)
            self.assertFalse(caught.exception.evidence[0]["ready"])

    def test_stale_lease_only_terminates_exact_mayapy_for_same_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            lock, journal = root / "queue.lock", root / "queue.json"
            executable = str(Path(r"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe").resolve())
            identity = ProcessIdentity(43210, executable, 123456)
            stale = {
                "token": "old", "pid": 123, "state": "运行中",
                "plan_sha256": "a" * 64, "journal_path": str(journal.resolve()),
                "worker": {"executable": executable, "identity": identity.to_dict()},
            }
            lease = QueueLease(lock, "a" * 64, journal)
            lease.metadata_path.write_text(json.dumps(stale), encoding="utf-8")
            lease.acquire()
            try:
                with mock.patch(
                    "MayaScope.process_guard.get_process_identity", return_value=identity
                ), mock.patch(
                    "MayaScope.process_guard.terminate_exact_process", return_value=True
                ) as terminate:
                    event = lease.recover_previous_worker()
                terminate.assert_called_once_with(identity, timeout=5.0)
                self.assertEqual(event["outcome"], "已终止验证孤儿")
            finally:
                lease.release()


if __name__ == "__main__":
    unittest.main()
