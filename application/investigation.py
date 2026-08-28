"""Coordinate one coherent investigation without importing Maya or PySide.

The coordinator accepts trusted analysis results, validates that they still
belong to the current scene generation, advances immutable presentation state,
and emits typed Atlas intentions.  The Qt workspace remains a thin renderer for
those intentions and the Maya boundary remains responsible for host I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Sequence, Tuple, Union

from ..analysis.clinic import ClinicReport
from ..analysis.counterfactual import CounterfactualReport
from ..analysis.delta import compare_snapshots
from ..analysis.identity import build_host_identity_index
from ..analysis.incidents import Incident
from ..analysis.lens import RootCauseCandidate, RootCauseReport, build_root_cause_report
from ..analysis.measured_lens import (
    MeasuredRootCauseReport,
    build_measured_root_cause_report,
)
from ..analysis.pulse import PulseNodeStat, node_stats
from ..analysis.rules import Issue
from ..model import ProfilerCapture, SceneSnapshot
from ..presentation import WorkspacePresentationState


class InvestigationStateError(ValueError):
    """A stale or inconsistent result attempted to enter the investigation."""


@dataclass(frozen=True)
class AtlasSceneIntent:
    snapshot: SceneSnapshot
    issues: Tuple[Issue, ...]
    priority_node_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AtlasHighlightIntent:
    node_ids: Tuple[str, ...]


@dataclass(frozen=True)
class AtlasLensIntent:
    report: RootCauseReport
    candidate: Optional[RootCauseCandidate] = None


@dataclass(frozen=True)
class AtlasSelectionIntent:
    node_ids: Tuple[str, ...]
    center: bool = False


@dataclass(frozen=True)
class AtlasPulseIntent:
    stats: Tuple[PulseNodeStat, ...]


@dataclass(frozen=True)
class AtlasCounterfactualIntent:
    report: CounterfactualReport


@dataclass(frozen=True)
class AtlasClearIntent:
    pass


AtlasIntent = Union[
    AtlasSceneIntent,
    AtlasHighlightIntent,
    AtlasLensIntent,
    AtlasSelectionIntent,
    AtlasPulseIntent,
    AtlasCounterfactualIntent,
    AtlasClearIntent,
]


@dataclass(frozen=True)
class InvestigationTransition:
    state: WorkspacePresentationState
    atlas_intents: Tuple[AtlasIntent, ...] = ()
    identity_index: Optional[Mapping[str, str]] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "atlas_intents", tuple(self.atlas_intents))
        if self.identity_index is not None:
            object.__setattr__(
                self,
                "identity_index",
                MappingProxyType(dict(self.identity_index)),
            )


@dataclass(frozen=True)
class HostSelectionDecision:
    outcome: str
    names: Tuple[str, ...]
    node_ids: Tuple[str, ...]
    transition: InvestigationTransition


def resolve_host_selection(
    snapshot: SceneSnapshot,
    names: Sequence[str],
    identity_index: Optional[Mapping[str, str]] = None,
) -> Tuple[str, ...]:
    """Resolve exact Maya names while refusing ambiguous short-name guesses."""
    identities = identity_index or build_host_identity_index(snapshot)
    resolved = []
    seen = set()
    for name in names:
        node_id = identities.get(str(name))
        if node_id is not None and node_id not in seen:
            seen.add(node_id)
            resolved.append(node_id)
    return tuple(resolved)


def _validate_clinic_result(
    snapshot: SceneSnapshot,
    report: ClinicReport,
    incidents: Sequence[Incident],
) -> None:
    if report.snapshot_id != snapshot.snapshot_id:
        raise InvestigationStateError(
            "场景诊所结果属于旧快照：%s，不是当前快照 %s"
            % (report.snapshot_id, snapshot.snapshot_id)
        )
    known_nodes = set(snapshot.node_map)
    issue_ids = [issue.id for issue in report.issues]
    if len(issue_ids) != len(set(issue_ids)):
        raise InvestigationStateError("场景诊所结果包含重复 Issue 身份")
    for issue in report.issues:
        missing = set(issue.affected_node_ids).difference(known_nodes)
        if missing:
            raise InvestigationStateError(
                "诊断 %s 引用了当前快照不存在的节点：%s"
                % (issue.id, sorted(missing)[0])
            )
    known_issues = set(issue_ids)
    incident_ids = [incident.id for incident in incidents]
    if len(incident_ids) != len(set(incident_ids)):
        raise InvestigationStateError("场景诊所结果包含重复事件簇身份")
    for incident in incidents:
        missing_issues = set(incident.issue_ids).difference(known_issues)
        missing_nodes = set(incident.affected_node_ids).difference(known_nodes)
        if missing_issues:
            raise InvestigationStateError(
                "事件簇 %s 引用了不存在的诊断：%s"
                % (incident.id, sorted(missing_issues)[0])
            )
        if missing_nodes:
            raise InvestigationStateError(
                "事件簇 %s 引用了当前快照不存在的节点：%s"
                % (incident.id, sorted(missing_nodes)[0])
            )


class InvestigationCoordinator:
    """Pure application coordinator for scene, Clinic, selection and Lens flow."""

    def accept_scene(
        self,
        state: WorkspacePresentationState,
        snapshot: SceneSnapshot,
        report: ClinicReport,
        incidents: Sequence[Incident],
        *,
        identity_index: Optional[Mapping[str, str]] = None,
        previous_snapshot: Optional[SceneSnapshot] = None,
    ) -> InvestigationTransition:
        _validate_clinic_result(snapshot, report, incidents)
        identities = identity_index or build_host_identity_index(snapshot)
        next_state = state.present_scene(
            snapshot,
            tuple(report.issues),
            report,
            tuple(incidents),
        )
        if previous_snapshot is not None:
            next_state = next_state.present_delta(
                compare_snapshots(previous_snapshot, snapshot),
                previous_snapshot,
            )
        priority = resolve_host_selection(
            snapshot,
            tuple(snapshot.metadata.get("selection", ())),
            identities,
        )
        return InvestigationTransition(
            next_state,
            (AtlasSceneIntent(snapshot, tuple(report.issues), priority),),
            identities,
        )

    def accept_clinic(
        self,
        state: WorkspacePresentationState,
        report: ClinicReport,
        incidents: Sequence[Incident],
        *,
        identity_index: Optional[Mapping[str, str]] = None,
    ) -> InvestigationTransition:
        snapshot = state.snapshot
        if snapshot is None:
            raise InvestigationStateError("没有当前场景，不能接收诊所结果")
        _validate_clinic_result(snapshot, report, incidents)
        identities = identity_index or build_host_identity_index(snapshot)
        priority = resolve_host_selection(
            snapshot,
            tuple(snapshot.metadata.get("selection", ())),
            identities,
        )
        next_state = state.present_clinic(report, tuple(incidents))
        return InvestigationTransition(
            next_state,
            (
                AtlasSceneIntent(snapshot, tuple(report.issues), priority),
                AtlasClearIntent(),
            ),
            identities,
        )

    def select_issue(
        self,
        state: WorkspacePresentationState,
        issue: Issue,
    ) -> InvestigationTransition:
        current = next((item for item in state.issues if item.id == issue.id), None)
        if current is None:
            raise InvestigationStateError("所选诊断不属于当前快照：%s" % issue.id)
        next_state = state.clear_lens().select_issue(current)
        return InvestigationTransition(
            next_state,
            (AtlasClearIntent(), AtlasHighlightIntent(tuple(current.affected_node_ids))),
        )

    def select_incident(
        self,
        state: WorkspacePresentationState,
        incident: Incident,
    ) -> InvestigationTransition:
        current = next(
            (item for item in state.incidents if item.id == incident.id),
            None,
        )
        if current is None:
            raise InvestigationStateError("所选事件簇不属于当前快照：%s" % incident.id)
        known_issues = {issue.id for issue in state.issues}
        if set(current.issue_ids).difference(known_issues):
            raise InvestigationStateError("所选事件簇包含已经失效的诊断")
        next_state = state.clear_lens().select_incident(current)
        return InvestigationTransition(
            next_state,
            (AtlasClearIntent(), AtlasHighlightIntent(tuple(current.affected_node_ids))),
        )

    def focus(
        self,
        state: WorkspacePresentationState,
        node_id: str,
        *,
        direction: str,
        max_depth: int,
    ) -> InvestigationTransition:
        snapshot = state.snapshot
        if snapshot is None or node_id not in snapshot.node_map:
            raise InvestigationStateError("焦点节点不属于当前快照：%s" % node_id)
        if direction not in {"upstream", "downstream"}:
            raise InvestigationStateError("不支持的根因透镜方向：%s" % direction)
        focused = state.focus(node_id)
        measured: Optional[MeasuredRootCauseReport]
        if state.profiler_capture is not None:
            measured = build_measured_root_cause_report(
                snapshot,
                state.profiler_capture,
                node_id,
                issues=state.issues,
                direction=direction,
                max_depth=max_depth,
                start_us=state.pulse_range[0],
                end_us=state.pulse_range[1],
            )
            report = measured.structural
        else:
            measured = None
            report = build_root_cause_report(
                snapshot,
                node_id,
                issues=state.issues,
                direction=direction,
                max_depth=max_depth,
            )
        next_state = focused.present_lens(report, measured)
        return InvestigationTransition(next_state, (AtlasLensIntent(report),))

    def select_candidate(
        self,
        state: WorkspacePresentationState,
        candidate: RootCauseCandidate,
    ) -> InvestigationTransition:
        report = state.lens_report
        if report is None:
            raise InvestigationStateError("当前没有根因透镜结果")
        current = next(
            (item for item in report.candidates if item.node_id == candidate.node_id),
            None,
        )
        if current is None:
            raise InvestigationStateError(
                "根因候选不属于当前透镜结果：%s" % candidate.node_id
            )
        next_state = state.update(selected_candidate=current)
        return InvestigationTransition(
            next_state,
            (AtlasLensIntent(report, current),),
        )

    def close_lens(
        self,
        state: WorkspacePresentationState,
    ) -> InvestigationTransition:
        next_state = state.clear_lens()
        if state.counterfactual_run is not None:
            intent: AtlasIntent = AtlasCounterfactualIntent(
                state.counterfactual_run.report
            )
        elif state.profiler_capture is not None:
            intent = AtlasPulseIntent(
                tuple(node_stats(state.profiler_capture, *state.pulse_range))
            )
        else:
            intent = AtlasClearIntent()
        return InvestigationTransition(next_state, (intent,))

    def host_selection(
        self,
        state: WorkspacePresentationState,
        names: Sequence[str],
        *,
        identity_index: Optional[Mapping[str, str]] = None,
        direction: str,
        max_depth: int,
        center: bool,
    ) -> HostSelectionDecision:
        snapshot = state.snapshot
        if snapshot is None:
            raise InvestigationStateError("没有当前场景，不能同步 Maya 选择")
        normalized = tuple(str(name) for name in names if name)
        node_ids = resolve_host_selection(snapshot, normalized, identity_index)
        if not normalized:
            closed = self.close_lens(state)
            transition = InvestigationTransition(
                closed.state,
                closed.atlas_intents + (AtlasSelectionIntent((), False),),
            )
            return HostSelectionDecision("empty", normalized, (), transition)
        if not node_ids:
            return HostSelectionDecision(
                "unmapped",
                normalized,
                (),
                InvestigationTransition(state),
            )
        selection = AtlasSelectionIntent(node_ids, center)
        if len(node_ids) == 1:
            focused = self.focus(
                state,
                node_ids[0],
                direction=direction,
                max_depth=max_depth,
            )
            transition = InvestigationTransition(
                focused.state,
                (selection,) + focused.atlas_intents,
            )
            return HostSelectionDecision("single", normalized, node_ids, transition)
        closed = self.close_lens(state)
        transition = InvestigationTransition(
            closed.state,
            closed.atlas_intents
            + (selection, AtlasHighlightIntent(node_ids)),
        )
        return HostSelectionDecision("multiple", normalized, node_ids, transition)


__all__ = [
    "AtlasClearIntent",
    "AtlasCounterfactualIntent",
    "AtlasHighlightIntent",
    "AtlasIntent",
    "AtlasLensIntent",
    "AtlasPulseIntent",
    "AtlasSceneIntent",
    "AtlasSelectionIntent",
    "HostSelectionDecision",
    "InvestigationCoordinator",
    "InvestigationStateError",
    "InvestigationTransition",
    "resolve_host_selection",
]
