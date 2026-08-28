from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.clinic import ClinicReport, RuleFailure, RuleRun
from MayaScope.analysis.incidents import Incident
from MayaScope.analysis.rules import Evidence, Issue, Severity
from MayaScope.presentation import ClinicEvidencePresenter, EvidencePanelState
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.clinic import SceneClinicView


class ClinicEvidencePresenterTests(unittest.TestCase):
    def setUp(self):
        self.issue = Issue(
            "issue:reference",
            "missing-reference-files",
            "引用文件缺失",
            "场景引用的角色文件无法读取。",
            Severity.ERROR,
            ("node-a",),
            (Evidence("路径", "D:/show/hero.ma"),),
        )
        self.incident = Incident(
            "incident:reference",
            "角色引用链中断",
            Severity.ERROR,
            (self.issue.id,),
            ("node-a",),
            (Evidence("根因", "上游角色文件缺失"),),
        )
        self.report = ClinicReport(
            "snapshot-a",
            (self.issue,),
            (RuleRun(self.issue.rule_id, 0.4, 1),),
            (),
            (),
        )

    def test_panel_state_rejects_blank_user_visible_content(self):
        with self.assertRaises(ValueError):
            EvidencePanelState("", "正文")
        with self.assertRaises(ValueError):
            EvidencePanelState("标题", " ")

    def test_overview_distinguishes_waiting_empty_failure_and_findings(self):
        waiting = ClinicEvidencePresenter.overview(None)
        self.assertEqual(waiting.heading, "等待场景信号")

        disabled = ClinicEvidencePresenter.overview(
            ClinicReport("snapshot-a", (), (), (), ())
        )
        self.assertIn("没有启用", disabled.heading)

        failed = ClinicEvidencePresenter.overview(
            ClinicReport(
                "snapshot-a",
                (),
                (RuleRun("safe-rule", 0.2, 0),),
                (RuleFailure("broken-rule", "执行超时"),),
                (),
            )
        )
        self.assertIn("规则异常已隔离", failed.body)
        self.assertIn("不会被误判为干净结果", failed.body)

        findings = ClinicEvidencePresenter.overview(
            self.report, (self.incident,)
        )
        self.assertEqual(findings.heading, "1 个事件簇 · 1 项发现")

    def test_issue_action_is_driven_by_verified_plan_availability(self):
        diagnostic = ClinicEvidencePresenter.issue(self.issue, has_plan=False)
        self.assertFalse(diagnostic.action_enabled)
        self.assertEqual(diagnostic.action_label, "仅提供诊断")
        self.assertIn("D:/show/hero.ma", diagnostic.body)

        repairable = ClinicEvidencePresenter.issue(self.issue, has_plan=True)
        self.assertTrue(repairable.action_enabled)
        self.assertEqual(repairable.action_label, "预览变更计划")

    def test_incident_requires_current_issue_identity_and_formats_undo_scope(self):
        with self.assertRaises(ValueError):
            ClinicEvidencePresenter.incident(self.incident, {})

        state = ClinicEvidencePresenter.incident(
            self.incident,
            {self.issue.id: self.issue},
            repairable_issue_count=2,
        )
        self.assertTrue(state.action_enabled)
        self.assertEqual(state.action_label, "预览批量变更计划")
        self.assertIn("Maya Undo 块", state.body)


class _RuleArrayStub(QtWidgets.QFrame):
    def __init__(self):
        super().__init__()
        self.compact = None

    def set_compact(self, compact):
        self.compact = bool(compact)


class SceneClinicViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.rule_array = _RuleArrayStub()
        self.view = SceneClinicView(self.rule_array)

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def test_view_owns_evidence_surface_and_compact_width(self):
        self.view.present_text(
            "运行时证据",
            "已读取 12 个回调。",
            action_label="只读宿主检查",
            action_enabled=False,
        )
        self.assertEqual(self.view.heading.text(), "运行时证据")
        self.assertEqual(self.view.evidence.text(), "已读取 12 个回调。")
        self.assertEqual(self.view.plan_button.text(), "只读宿主检查")
        self.view.set_compact(True)
        self.assertTrue(self.rule_array.compact)
        self.assertEqual(self.view.maximumWidth(), 330)

    def test_report_cards_forward_issue_and_incident_signals(self):
        issue = Issue(
            "issue:a",
            "rule-a",
            "节点异常",
            "测试视图信号。",
            Severity.WARNING,
            ("a",),
            (Evidence("节点", "a"),),
        )
        incident = Incident(
            "incident:a",
            "节点事件",
            Severity.WARNING,
            (issue.id,),
            ("a",),
            (Evidence("范围", "1 个节点"),),
        )
        report = ClinicReport(
            "snapshot-a",
            (issue,),
            (RuleRun("rule-a", 0.1, 1),),
            (),
            (),
        )
        self.view.render_report(report, (incident,), {})
        self.assertEqual(self.view.heading.text(), "1 个事件簇 · 1 项发现")
        self.assertEqual(self.view.issue_list.count(), 3)

    def test_workspace_no_longer_builds_or_writes_evidence_widgets_directly(self):
        ui_root = Path(__file__).resolve().parents[1] / "ui"
        workspace = (ui_root / "workspace.py").read_text(encoding="utf-8")
        self.assertNotIn("self.issue_heading", workspace)
        self.assertNotIn("self.evidence", workspace)
        self.assertNotIn("self.plan_button", workspace)
        self.assertIn("from .clinic import SceneClinicView", workspace)


if __name__ == "__main__":
    unittest.main()
