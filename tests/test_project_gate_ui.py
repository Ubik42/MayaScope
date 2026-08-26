from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.workspace import ProjectGateStrip


class ProjectGateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_verified_project_payload_drives_chinese_release_train(self):
        strip = ProjectGateStrip()
        payload = {
            "project_sha256": "a" * 64,
            "gate_failed": True,
            "summary": {
                "scene_count": 2,
                "passed_scene_count": 1,
                "blocked_scene_count": 1,
                "atomic_finding_count": 3,
            },
            "scenes": (
                {"receipt": {
                    "source_scene": "D:/show/shot010.ma", "ok": True,
                    "gate_failed": False, "issue_count": 0,
                    "atomic_finding_count": 0, "report_sha256": "b" * 64,
                }},
                {"receipt": {
                    "source_scene": "D:/show/shot020.ma", "ok": True,
                    "gate_failed": True, "issue_count": 2,
                    "atomic_finding_count": 3, "report_sha256": "c" * 64,
                }},
            ),
        }
        strip.set_report(payload)
        self.assertEqual(strip.verdict.text(), "发布已阻断")
        self.assertIn("2 个场景", strip.detail.text())
        self.assertIn("原子发现 3", strip.detail.text())
        self.assertTrue(strip.isVisible())
        strip.set_motion_enabled(False)
        self.assertFalse(strip.canvas._timer.isActive())

    def test_resumable_queue_states_are_visible_and_actionable_in_chinese(self):
        strip = ProjectGateStrip()
        journal = {
            "state": "运行中",
            "journal_sha256": "d" * 64,
            "recovery_count": 1,
            "summary": {
                "scene_count": 3, "pending": 1, "running": 1,
                "passed": 1, "blocked": 0, "failed": 0,
            },
            "jobs": (
                {"source_scene": "D:/show/a.ma", "status": "通过", "attempts": 1},
                {"source_scene": "D:/show/b.ma", "status": "运行中", "attempts": 2,
                 "worker": {"pid": 24680, "job_kill_on_close": True}},
                {"source_scene": "D:/show/c.ma", "status": "待运行", "attempts": 0},
            ),
            "storage_preflight": ({
                "free_bytes": 3 * 1073741824,
                "required_bytes": 1073741824,
                "ready": True,
            },),
        }
        strip.set_queue(journal)
        self.assertEqual(strip.verdict.text(), "项目审计运行中")
        self.assertEqual(strip.queue_action.text(), "安全暂停")
        self.assertIn("恢复 1 次", strip.identity.text())
        self.assertIn("容量余量 2.0 GiB", strip.guard.text())
        self.assertIn("Maya PID 24680", strip.guard.text())
        self.assertIn("崩溃联动开启", strip.guard.text())
        self.assertEqual(strip.canvas._scenes[1]["receipt"]["queue_status"], "运行中")
        journal["state"] = "已暂停"
        strip.set_queue(journal)
        self.assertEqual(strip.queue_action.text(), "继续队列")

    def test_storage_preflight_failure_is_not_hidden(self):
        strip = ProjectGateStrip()
        strip.set_queue({
            "state": "预检失败",
            "journal_sha256": "e" * 64,
            "summary": {"scene_count": 1, "pending": 1, "running": 0,
                        "passed": 0, "blocked": 0, "failed": 0},
            "jobs": ({"source_scene": "D:/show/a.ma", "status": "待运行"},),
            "storage_preflight": ({
                "free_bytes": 10, "required_bytes": 20, "ready": False,
            },),
        })
        self.assertEqual(strip.verdict.text(), "磁盘容量预检未通过")
        self.assertIn("磁盘容量预检未通过", strip.guard.text())
        self.assertTrue(strip.guard.property("alert"))


if __name__ == "__main__":
    unittest.main()
