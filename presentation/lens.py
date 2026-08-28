"""Validated Chinese presentation state for structural and measured Lens evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from ..analysis.lens import RootCauseCandidate, RootCauseReport
from ..analysis.measured_lens import MeasuredRootCauseReport
from ..model import SceneSnapshot


class LensPresentationError(ValueError):
    """Raised when a Lens generation cannot be rendered without guessing."""


@dataclass(frozen=True)
class LensCandidateCardState:
    candidate: RootCauseCandidate
    rank: int
    signal: str
    name: str
    detail: str
    tooltip: str
    measured: bool = False


@dataclass(frozen=True)
class LensResultState:
    cards: Tuple[LensCandidateCardState, ...]
    summary: str
    summary_tooltip: str
    status: str
    empty_body: str


@dataclass(frozen=True)
class LensCandidateEvidenceState:
    heading: str
    body: str


def _validate_report(report: RootCauseReport, snapshot: SceneSnapshot) -> None:
    if report.direction not in {"upstream", "downstream"}:
        raise LensPresentationError("根因透镜包含未知追踪方向")
    if report.focus_node_id not in snapshot.node_map:
        raise LensPresentationError("根因透镜焦点不属于当前快照")
    seen = set()
    for candidate in report.candidates:
        if candidate.node_id in seen:
            raise LensPresentationError("根因透镜包含重复候选：%s" % candidate.node_id)
        seen.add(candidate.node_id)
        if candidate.node_id not in snapshot.node_map:
            raise LensPresentationError("根因候选不属于当前快照：%s" % candidate.node_id)
        if not candidate.path_node_ids or any(
            node_id not in snapshot.node_map for node_id in candidate.path_node_ids
        ):
            raise LensPresentationError("根因候选缺少完整的当前代路径")
        expected_ends = (
            (candidate.node_id, report.focus_node_id)
            if report.direction == "upstream"
            else (report.focus_node_id, candidate.node_id)
        )
        if (candidate.path_node_ids[0], candidate.path_node_ids[-1]) != expected_ends:
            raise LensPresentationError("根因候选路径方向与报告不一致")


def _measured_by_node(
    report: RootCauseReport,
    measured_report: Optional[MeasuredRootCauseReport],
) -> dict:
    if measured_report is None:
        return {}
    if measured_report.structural.focus_node_id != report.focus_node_id:
        raise LensPresentationError("实测透镜与结构透镜焦点不一致")
    measured = {}
    report_ids = {candidate.node_id for candidate in report.candidates}
    for item in measured_report.candidates:
        node_id = item.structural.node_id
        if node_id not in report_ids or node_id in measured:
            raise LensPresentationError("实测候选与当前结构候选不一致")
        measured[node_id] = item
    return measured


def present_lens_result(
    report: RootCauseReport,
    snapshot: SceneSnapshot,
    measured_report: Optional[MeasuredRootCauseReport] = None,
) -> LensResultState:
    _validate_report(report, snapshot)
    measured_by_node = _measured_by_node(report, measured_report)
    cards = []
    for rank, candidate in enumerate(report.candidates, 1):
        node = snapshot.node_map[candidate.node_id]
        measured = measured_by_node.get(candidate.node_id)
        if measured is None:
            signal = "%02d  结构信号  %.1f" % (rank, candidate.structural_score)
        else:
            signal = "%02d  实测  %.2f ms  ·  %s 个事件" % (
                rank,
                measured.observed_inclusive_us / 1000.0,
                measured.observed_event_count,
            )
        cards.append(
            LensCandidateCardState(
                candidate=candidate,
                rank=rank,
                signal=signal,
                name=node.name,
                detail="%s  ·  距离 %s 跳" % (node.type_name, candidate.distance),
                tooltip="\n".join(candidate.reasons),
                measured=measured is not None,
            )
        )
    suffix = " · 已截断：%s" % report.truncation_reason if report.truncated else ""
    telemetry = "%s 节点 / %s 边 · %.2f ms" % (
        report.scanned_node_count,
        report.scanned_edge_count,
        report.query_elapsed_ms,
    )
    if measured_report:
        summary = "实测覆盖 %.0f%% · %s%s" % (
            measured_report.measurement_coverage * 100.0,
            telemetry,
            suffix,
        )
        mode = "实测 + 结构"
    else:
        summary = "结构推断 · %s%s" % (telemetry, suffix)
        mode = "结构推断"
    direction = "上游" if report.direction == "upstream" else "影响域"
    reuse = snapshot.metadata.get("capture_reuse", {})
    reuse_status = "  ·  CSR 已复用" if reuse.get("topology_unchanged") else ""
    status = (
        "  根因透镜  ·  %s  ·  %s  ·  %s 节点 / %s 边  ·  %.2f ms  ·  %s 个候选%s%s"
        % (
            mode,
            direction,
            report.scanned_node_count,
            report.scanned_edge_count,
            report.query_elapsed_ms,
            len(report.candidates),
            "  ·  已截断：%s" % report.truncation_reason if report.truncated else "",
            reuse_status,
        )
    )
    empty_body = (
        "在深度 %s 内未找到%s DG 候选。\n\n"
        "这说明结构范围为空，但不能证明该症状没有运行时原因。"
        % (report.max_depth, "上游" if report.direction == "upstream" else "下游")
    )
    tooltip = "查询内核在 %.3f ms 内扫描了 %s 个节点与 %s 条边%s。" % (
        report.query_elapsed_ms,
        report.scanned_node_count,
        report.scanned_edge_count,
        "；停止原因：%s" % report.truncation_reason if report.truncated else "",
    )
    return LensResultState(tuple(cards), summary, tooltip, status, empty_body)


def present_lens_candidate(
    candidate: RootCauseCandidate,
    report: RootCauseReport,
    snapshot: SceneSnapshot,
    measured_report: Optional[MeasuredRootCauseReport] = None,
) -> LensCandidateEvidenceState:
    _validate_report(report, snapshot)
    current = next(
        (item for item in report.candidates if item.node_id == candidate.node_id),
        None,
    )
    if current is None:
        raise LensPresentationError("根因候选不属于当前透镜结果")
    candidate = current
    node_map = snapshot.node_map
    node = node_map[candidate.node_id]
    path = "  →  ".join(node_map[node_id].name for node_id in candidate.path_node_ids)
    plugs = []
    for link in candidate.path_links:
        if link.source_id not in node_map or link.target_id not in node_map:
            raise LensPresentationError("根因候选 Plug 路径不属于当前快照")
        source = link.source_plug or node_map[link.source_id].name
        target = link.target_plug or node_map[link.target_id].name
        plugs.append("%s  →  %s" % (source, target))
    factors = "\n".join(
        "%s  ·  %s" % (item.label, item.value)
        for item in candidate.evidence
        if item.value not in {"0", "0.0"}
    ) or "无额外评分因素"
    reasons = "\n".join("• %s" % reason for reason in candidate.reasons)
    plug_text = "\n".join(plugs) if plugs else "节点身份直接命中"
    measured = _measured_by_node(report, measured_report).get(candidate.node_id)
    measurement = ""
    if measured and measured_report:
        measurement = (
            "选定范围内的实测结果\n"
            "包含耗时 %.3f ms  ·  %s 个事件  ·  占已映射耗时 %.1f%%\n"
            "路径包含耗时 %.3f ms  ·  覆盖率 %.0f%%\n"
            "范围 %.3f–%.3f ms\n"
            "包含事件可能互相重叠；这是观测证据，不代表预计优化收益。\n\n"
            % (
                measured.observed_inclusive_us / 1000.0,
                measured.observed_event_count,
                measured.observed_capture_share * 100.0,
                measured.path_inclusive_us / 1000.0,
                measured_report.measurement_coverage * 100.0,
                measured_report.selection_start_us / 1000.0,
                measured_report.selection_end_us / 1000.0,
            )
        )
    body = (
        "%s结构信号 %.1f / 99\n该分数不是概率\n\n%s\n\n因果路径\n%s\n\n"
        "Plug 证据\n%s\n\n评分因素\n%s"
        % (measurement, candidate.structural_score, reasons, path, plug_text, factors)
    )
    return LensCandidateEvidenceState(node.name, body)


__all__ = [
    "LensCandidateCardState",
    "LensCandidateEvidenceState",
    "LensPresentationError",
    "LensResultState",
    "present_lens_candidate",
    "present_lens_result",
]
