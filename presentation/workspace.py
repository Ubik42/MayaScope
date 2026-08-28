"""Immutable user-visible investigation state, independent from Maya and Qt."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Tuple


@dataclass(frozen=True)
class WorkspacePresentationState:
    """The coherent evidence currently presented by the investigation workspace.

    Runtime resources such as QThreads, timers, callbacks and capture sessions do
    not belong here.  This state only describes what the user is investigating
    and lets one semantic transition replace a group of formerly independent
    QWidget fields.
    """

    snapshot: Any = None
    issues: Tuple[Any, ...] = ()
    clinic_report: Any = None
    incidents: Tuple[Any, ...] = ()
    selected_issue: Any = None
    selected_incident: Any = None
    focus_node_id: str | None = None
    lens_report: Any = None
    measured_report: Any = None
    selected_candidate: Any = None
    profiler_capture: Any = None
    counterfactual_run: Any = None
    counterfactual_record: Any = None
    pulse_range: Tuple[int, int] = (0, 0)
    delta: Any = None
    delta_before: Any = None
    runtime_snapshot: Any = None
    runtime_report: Any = None

    def update(self, **changes: Any) -> "WorkspacePresentationState":
        """Return a new state while rejecting misspelled presentation fields."""
        unknown = set(changes).difference(self.__dataclass_fields__)
        if unknown:
            raise TypeError("未知呈现状态字段：%s" % ", ".join(sorted(unknown)))
        return replace(self, **changes)

    def present_scene(
        self,
        snapshot: Any,
        issues: Tuple[Any, ...],
        clinic_report: Any,
        incidents: Tuple[Any, ...],
    ) -> "WorkspacePresentationState":
        """Present one new scene generation and invalidate all older evidence."""
        return WorkspacePresentationState(
            snapshot=snapshot,
            issues=tuple(issues),
            clinic_report=clinic_report,
            incidents=tuple(incidents),
        )

    def present_clinic(
        self, report: Any, incidents: Tuple[Any, ...]
    ) -> "WorkspacePresentationState":
        """Replace findings for the same scene and clear stale selection/lens."""
        return replace(
            self,
            issues=tuple(report.issues),
            clinic_report=report,
            incidents=tuple(incidents),
            selected_issue=None,
            selected_incident=None,
            focus_node_id=None,
            lens_report=None,
            measured_report=None,
            selected_candidate=None,
        )

    def select_issue(self, issue: Any) -> "WorkspacePresentationState":
        return replace(self, selected_issue=issue, selected_incident=None)

    def select_incident(self, incident: Any) -> "WorkspacePresentationState":
        return replace(self, selected_issue=None, selected_incident=incident)

    def focus(self, node_id: str) -> "WorkspacePresentationState":
        return replace(
            self,
            selected_issue=None,
            selected_incident=None,
            focus_node_id=node_id,
        )

    def present_lens(
        self, report: Any, measured_report: Any = None
    ) -> "WorkspacePresentationState":
        return replace(
            self,
            lens_report=report,
            measured_report=measured_report,
            selected_candidate=None,
        )

    def clear_lens(self) -> "WorkspacePresentationState":
        return replace(
            self,
            focus_node_id=None,
            lens_report=None,
            measured_report=None,
            selected_candidate=None,
        )

    def present_delta(self, delta: Any, before: Any) -> "WorkspacePresentationState":
        return replace(self, delta=delta, delta_before=before)

    def present_runtime(
        self, snapshot: Any, report: Any
    ) -> "WorkspacePresentationState":
        return replace(self, runtime_snapshot=snapshot, runtime_report=report)

    def present_profiler(self, capture: Any) -> "WorkspacePresentationState":
        duration = int(getattr(capture, "duration_us", 0))
        return replace(self, profiler_capture=capture, pulse_range=(0, duration))

    def present_counterfactual(
        self, run: Any, record: Any = None
    ) -> "WorkspacePresentationState":
        return replace(self, counterfactual_run=run, counterfactual_record=record)

    def as_debug_mapping(self) -> Mapping[str, Any]:
        """Small stable summary for tests and future structured UI diagnostics."""
        return {
            "has_snapshot": self.snapshot is not None,
            "issue_count": len(self.issues),
            "incident_count": len(self.incidents),
            "focus_node_id": self.focus_node_id or "",
            "has_profiler": self.profiler_capture is not None,
            "has_runtime": self.runtime_snapshot is not None,
            "has_delta": self.delta is not None,
        }
