"""Scene Clinic rail and evidence surface for the MayaScope workspace."""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..analysis.clinic import ClinicReport, RuleSpec
from ..analysis.incidents import Incident
from ..analysis.rules import Issue
from ..presentation.evidence import ClinicEvidencePresenter, EvidencePanelState
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import qt_enum as _qt_enum


class IncidentCard(QtWidgets.QFrame):
    activated = QtCore.Signal(object)

    def __init__(self, incident: Incident, ordinal: int, parent=None):
        super().__init__(parent)
        self.incident = incident
        self.setObjectName("IncidentCard")
        self.setAccessibleName("事件簇：%s" % incident.title)
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        index = QtWidgets.QLabel(
            "事件簇 %02d  /  %s 项发现  /  %s 个节点"
            % (ordinal, len(incident.issue_ids), len(incident.affected_node_ids))
        )
        index.setObjectName("IncidentIndex")
        layout.addWidget(index)
        title = QtWidgets.QLabel(incident.title)
        title.setObjectName("IncidentTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        reason = QtWidgets.QLabel("  ·  ".join(item.value for item in incident.evidence[:2]))
        reason.setObjectName("IncidentReason")
        reason.setWordWrap(True)
        layout.addWidget(reason)

    def mousePressEvent(self, event):
        self.activated.emit(self.incident)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (
            _qt_enum(QtCore.Qt, "Key_Return"),
            _qt_enum(QtCore.Qt, "Key_Space"),
        ):
            self.activated.emit(self.incident)
            event.accept()
            return
        super().keyPressEvent(event)


class IssueCard(QtWidgets.QFrame):
    activated = QtCore.Signal(object)

    def __init__(self, issue: Issue, spec: Optional[RuleSpec] = None, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("IssueCard")
        self.setAccessibleName("诊断发现：%s" % issue.title)
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(5)
        title = QtWidgets.QLabel(issue.title)
        title.setObjectName("IssueTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        severity_name = {
            "INFO": "提示",
            "WARNING": "警告",
            "ERROR": "错误",
            "CRITICAL": "严重",
        }.get(issue.severity.name, issue.severity.name)
        severity = QtWidgets.QLabel(
            "%s  /  %s 个信号" % (severity_name, len(issue.affected_node_ids))
        )
        severity.setObjectName("Severity%s" % issue.severity.name.title())
        layout.addWidget(severity)
        if spec:
            category = {
                "integrity": "完整性",
                "performance": "性能",
                "references": "引用",
                "pipeline": "流程",
            }.get(spec.category, spec.category)
            confidence = {
                "deterministic": "确定性",
                "strong": "高置信",
                "heuristic": "启发式",
            }.get(spec.confidence, spec.confidence)
            cost = {
                "cheap": "轻量",
                "moderate": "常规",
                "expensive": "深度",
            }.get(spec.cost, spec.cost)
            repair = {
                "diagnostic": "仅诊断",
                "previewed": "可预览修复",
            }.get(spec.repair_kind, spec.repair_kind)
            contract = QtWidgets.QLabel(
                "%s  ·  %s  ·  %s扫描  ·  %s"
                % (category, confidence, cost, repair)
            )
            contract.setObjectName("IssueContract")
            contract.setWordWrap(True)
            layout.addWidget(contract)

    def mousePressEvent(self, event):
        self.activated.emit(self.issue)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (
            _qt_enum(QtCore.Qt, "Key_Return"),
            _qt_enum(QtCore.Qt, "Key_Space"),
        ):
            self.activated.emit(self.issue)
            event.accept()
            return
        super().keyPressEvent(event)


class SceneClinicView(QtWidgets.QFrame):
    """Own the Clinic cards and the shared evidence/action surface."""

    issueActivated = QtCore.Signal(object)
    incidentActivated = QtCore.Signal(object)
    planRequested = QtCore.Signal()
    rollbackRequested = QtCore.Signal()

    def __init__(self, rule_array, parent=None):
        super().__init__(parent)
        self.setObjectName("IssueRail")
        self.setAccessibleName("场景诊所问题与因果证据")
        self.setMinimumWidth(320)
        self.setMaximumWidth(430)
        self.rule_array = rule_array
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        eyebrow = QtWidgets.QLabel("问题证据")
        eyebrow.setObjectName("Eyebrow")
        layout.addWidget(eyebrow)
        self.heading = QtWidgets.QLabel("等待场景信号")
        self.heading.setObjectName("RailHeading")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        layout.addWidget(rule_array)

        self.issue_scroll = QtWidgets.QScrollArea()
        self.issue_scroll.setWidgetResizable(True)
        self.issue_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.issue_scroll.setHorizontalScrollBarPolicy(
            _qt_enum(QtCore.Qt, "ScrollBarAlwaysOff")
        )
        self.issue_host = QtWidgets.QWidget()
        self.issue_host.setMinimumWidth(0)
        self.issue_host.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,
            QtWidgets.QSizePolicy.Preferred,
        )
        self.issue_list = QtWidgets.QVBoxLayout(self.issue_host)
        self.issue_list.setContentsMargins(0, 8, 0, 8)
        self.issue_list.setSpacing(9)
        self.issue_list.addStretch(1)
        self.issue_scroll.setWidget(self.issue_host)
        layout.addWidget(self.issue_scroll, 1)

        self.evidence = QtWidgets.QLabel("捕获场景后将在这里呈现因果证据。")
        self.evidence.setObjectName("Evidence")
        self.evidence.setWordWrap(True)
        layout.addWidget(self.evidence)
        self.plan_button = QtWidgets.QPushButton("预览变更计划")
        self.plan_button.setObjectName("PlanButton")
        self.plan_button.setEnabled(False)
        self.plan_button.clicked.connect(self.planRequested)
        layout.addWidget(self.plan_button)
        self.rollback_button = QtWidgets.QPushButton("↶  回滚上次变更计划")
        self.rollback_button.setObjectName("RollbackButton")
        self.rollback_button.setVisible(False)
        self.rollback_button.clicked.connect(self.rollbackRequested)
        layout.addWidget(self.rollback_button)

    def set_compact(self, compact: bool):
        self.setMinimumWidth(270 if compact else 320)
        self.setMaximumWidth(330 if compact else 430)
        self.rule_array.set_compact(compact)

    def present(self, state: EvidencePanelState):
        self.heading.setText(state.heading)
        self.evidence.setText(state.body)
        self.plan_button.setText(state.action_label)
        self.plan_button.setEnabled(state.action_enabled)

    def set_heading(self, heading: str):
        if not heading.strip():
            raise ValueError("证据标题不能为空")
        self.heading.setText(heading)

    def set_body(self, body: str):
        if not body.strip():
            raise ValueError("证据正文不能为空")
        self.evidence.setText(body)

    def set_action(self, label: str, *, enabled: bool):
        if not label.strip():
            raise ValueError("证据操作文案不能为空")
        self.plan_button.setText(label)
        self.plan_button.setEnabled(enabled)

    def present_text(
        self,
        heading: str,
        body: str,
        *,
        action_label: str = "预览变更计划",
        action_enabled: bool = False,
    ):
        self.present(
            EvidencePanelState(
                heading=heading,
                body=body,
                action_label=action_label,
                action_enabled=action_enabled,
            )
        )

    def render_report(
        self,
        report: ClinicReport,
        incidents: Sequence[Incident],
        specs: Mapping[str, RuleSpec],
    ):
        self._clear_cards()
        issues_by_id = {issue.id: issue for issue in report.issues}
        for ordinal, incident in enumerate(incidents, 1):
            incident_card = IncidentCard(incident, ordinal)
            incident_card.activated.connect(self.incidentActivated)
            self.issue_list.insertWidget(self.issue_list.count() - 1, incident_card)
            for issue_id in incident.issue_ids:
                issue = issues_by_id.get(issue_id)
                if issue is None:
                    raise ValueError("事件簇引用了不存在的诊断：%s" % issue_id)
                card = IssueCard(issue, specs.get(issue.rule_id))
                card.activated.connect(self.issueActivated)
                self.issue_list.insertWidget(self.issue_list.count() - 1, card)
        self.present(ClinicEvidencePresenter.overview(report, incidents))

    def present_issue(self, issue: Issue, *, has_plan: bool):
        self.present(ClinicEvidencePresenter.issue(issue, has_plan=has_plan))

    def present_incident(
        self,
        incident: Incident,
        issue_map: Mapping[str, Issue],
        *,
        repairable_issue_count: int = 0,
    ):
        self.present(
            ClinicEvidencePresenter.incident(
                incident,
                issue_map,
                repairable_issue_count=repairable_issue_count,
            )
        )

    def _clear_cards(self):
        while self.issue_list.count() > 1:
            item = self.issue_list.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
