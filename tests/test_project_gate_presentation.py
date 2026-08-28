from __future__ import annotations

from pathlib import Path
import unittest

from MayaScope.presentation import (
    ProjectGatePresentationError,
    present_project_fault,
    present_project_queue,
    present_project_report,
)


class ProjectGatePresentationTests(unittest.TestCase):
    def test_verified_report_becomes_immutable_chinese_gate_state(self):
        state = present_project_report(
            {
                "project_sha256": "a" * 64,
                "gate_failed": True,
                "summary": {
                    "scene_count": 2,
                    "passed_scene_count": 1,
                    "blocked_scene_count": 1,
                    "atomic_finding_count": 2,
                },
                "scenes": (
                    {
                        "receipt": {
                            "source_scene": "D:/show/shot010.ma",
                            "ok": True,
                            "gate_failed": False,
                            "issue_count": 0,
                            "atomic_finding_count": 0,
                            "report_sha256": "b" * 64,
                        }
                    },
                    {
                        "receipt": {
                            "source_scene": "D:/show/shot020.ma",
                            "ok": True,
                            "gate_failed": True,
                            "issue_count": 1,
                            "atomic_finding_count": 2,
                            "report_sha256": "c" * 64,
                        }
                    },
                ),
            }
        )
        self.assertEqual(state.verdict, "发布已阻断")
        self.assertEqual(state.guard, "✓ 双层签名已验证")
        self.assertEqual(state.scenes[1].display_name, "shot020")
        self.assertTrue(state.scenes[1].blocked)

    def test_queue_state_exposes_capacity_worker_and_safe_pause(self):
        state = present_project_queue(
            {
                "state": "运行中",
                "journal_sha256": "d" * 64,
                "recovery_count": 2,
                "summary": {
                    "scene_count": 3,
                    "passed": 1,
                    "blocked": 0,
                    "failed": 0,
                    "pending": 1,
                },
                "jobs": (
                    {"source_scene": "D:/show/a.ma", "status": "通过", "attempts": 1},
                    {
                        "source_scene": "D:/show/b.ma",
                        "status": "运行中",
                        "attempts": 2,
                        "worker": {"pid": 24680, "job_kill_on_close": True},
                    },
                    {"source_scene": "D:/show/c.ma", "status": "待运行"},
                ),
                "storage_preflight": (
                    {
                        "free_bytes": 3 * 1073741824,
                        "required_bytes": 1073741824,
                        "ready": True,
                    },
                ),
            }
        )
        self.assertEqual(state.verdict, "项目审计运行中")
        self.assertEqual(state.action_text, "安全暂停")
        self.assertTrue(state.action_enabled)
        self.assertIn("容量余量 2.0 GiB", state.guard)
        self.assertIn("Maya PID 24680", state.guard)

    def test_inconsistent_or_unidentified_evidence_fails_closed(self):
        with self.assertRaisesRegex(ProjectGatePresentationError, "SHA-256"):
            present_project_report(
                {
                    "project_sha256": "not-a-signature",
                    "summary": {},
                    "scenes": (),
                }
            )
        with self.assertRaisesRegex(ProjectGatePresentationError, "数量不一致"):
            present_project_queue(
                {
                    "state": "运行中",
                    "journal_sha256": "e" * 64,
                    "summary": {"scene_count": 2},
                    "jobs": ({"source_scene": "D:/show/a.ma"},),
                }
            )

    def test_fault_state_explains_what_was_protected(self):
        state = present_project_fault("队列已由其他进程接管", "锁文件属于 PID 123")
        self.assertTrue(state.failed)
        self.assertTrue(state.guard_alert)
        self.assertIn("不会并发启动 Maya", state.guard)

    def test_presenter_has_no_qt_maya_or_view_dependency(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "presentation"
            / "project_gate.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in ("pyside", "qtwidgets", "maya.cmds", "collectors", "ui."):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
