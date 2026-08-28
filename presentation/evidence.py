"""Host-independent presentation models for the shared evidence rail.

The evidence rail is reused by Clinic, Lens, Profiler, runtime and recovery
workflows.  This module owns user-facing Clinic wording without importing Qt or
Maya, so state formatting can be verified independently from widget lifetime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from ..analysis.clinic import ClinicReport
from ..analysis.incidents import Incident
from ..analysis.rules import Issue


@dataclass(frozen=True)
class EvidencePanelState:
    """Complete, immutable content for the shared evidence surface."""

    heading: str
    body: str
    action_label: str = "预览变更计划"
    action_enabled: bool = False

    def __post_init__(self):
        if not self.heading.strip():
            raise ValueError("证据标题不能为空")
        if not self.body.strip():
            raise ValueError("证据正文不能为空")
        if not self.action_label.strip():
            raise ValueError("证据操作文案不能为空")


class ClinicEvidencePresenter:
    """Format Clinic results without reading widgets or mutating scene state."""

    @staticmethod
    def overview(
        report: Optional[ClinicReport],
        incidents: Sequence[Incident] = (),
    ) -> EvidencePanelState:
        if report is None:
            return EvidencePanelState(
                heading="等待场景信号",
                body="捕获场景后将在这里呈现因果证据。",
            )
        if not report.runs:
            return EvidencePanelState(
                heading="没有启用场景诊所规则",
                body="请至少启用一条诊所规则，然后扫描已冻结的场景快照。",
            )
        if report.failures:
            failures = "\n".join(
                "%s  ·  %s" % (item.rule_id, item.message)
                for item in report.failures
            )
            return EvidencePanelState(
                heading="%s 项发现 · %s 条规则异常"
                % (len(report.issues), len(report.failures)),
                body=(
                    "规则异常已隔离\n\n%s\n\n"
                    "其余规则已完成；异常规则不会被误判为干净结果。"
                )
                % failures,
            )
        heading = (
            "%s 个事件簇 · %s 项发现" % (len(incidents), len(report.issues))
            if report.issues
            else "场景信号正常"
        )
        return EvidencePanelState(
            heading=heading,
            body=(
                "选择一个异常，查看证据与受影响拓扑。"
                if report.issues
                else "当前规则组合没有发现异常；可切换规则组合或重新捕获场景。"
            ),
        )

    @staticmethod
    def issue(issue: Issue, *, has_plan: bool) -> EvidencePanelState:
        evidence = "\n".join(
            "%s  ·  %s" % (item.label, item.value) for item in issue.evidence
        )
        sections = [issue.description]
        if evidence:
            sections.append(evidence)
        sections.append(issue.id)
        return EvidencePanelState(
            heading=issue.title,
            body="\n\n".join(sections),
            action_label="预览变更计划" if has_plan else "仅提供诊断",
            action_enabled=has_plan,
        )

    @staticmethod
    def incident(
        incident: Incident,
        issue_map: Mapping[str, Issue],
        *,
        repairable_issue_count: int = 0,
    ) -> EvidencePanelState:
        missing = tuple(
            issue_id for issue_id in incident.issue_ids if issue_id not in issue_map
        )
        if missing:
            raise ValueError("事件簇引用了不存在的诊断：%s" % ", ".join(missing))
        findings = "\n".join(
            "• %s  [%s]" % (issue_map[issue_id].title, issue_map[issue_id].severity.name)
            for issue_id in incident.issue_ids
        )
        evidence = "\n".join(
            "%s  ·  %s" % (item.label, item.value) for item in incident.evidence
        )
        repair_note = (
            "%s 项可修复发现可合并到一个经验证的 Maya Undo 块中。"
            % repairable_issue_count
            if repairable_issue_count
            else "该事件簇仅提供诊断，不建议自动修改场景。"
        )
        has_plan = repairable_issue_count > 0
        return EvidencePanelState(
            heading=incident.title,
            body=(
                "事件簇范围\n%s\n\n关联证据\n%s\n\n"
                "诊断发现\n%s\n\n批处理意图\n%s"
            )
            % (incident.id, evidence or "无附加证据", findings, repair_note),
            action_label=(
                "预览批量变更计划"
                if repairable_issue_count > 1
                else "预览事件簇变更计划"
                if has_plan
                else "仅诊断事件簇"
            ),
            action_enabled=has_plan,
        )
