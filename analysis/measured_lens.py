"""Profiler-measured evidence layered onto the structural Root Cause Lens."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from .lens import RootCauseCandidate, RootCauseReport, build_root_cause_report
from .pulse import node_stats
from .rules import Issue
from ..model import ProfilerCapture, SceneSnapshot


@dataclass(frozen=True)
class MeasuredCandidate:
    structural: RootCauseCandidate
    observed_inclusive_us: int
    observed_event_count: int
    observed_capture_share: float
    path_inclusive_us: int


@dataclass(frozen=True)
class MeasuredRootCauseReport:
    structural: RootCauseReport
    capture_id: str
    selection_start_us: int
    selection_end_us: int
    candidates: Tuple[MeasuredCandidate, ...]
    mapped_event_count: int
    selected_event_count: int

    @property
    def measurement_coverage(self) -> float:
        if not self.selected_event_count:
            return 0.0
        return self.mapped_event_count / float(self.selected_event_count)


def build_measured_root_cause_report(
    snapshot: SceneSnapshot,
    capture: ProfilerCapture,
    focus_node_id: str,
    issues: Sequence[Issue] = (),
    direction: str = "upstream",
    max_depth: int = 4,
    start_us: int = 0,
    end_us: Optional[int] = None,
    candidate_limit: int = 6,
) -> MeasuredRootCauseReport:
    """Rank structural suspects by observed activity in one selected time range.

    Inclusive duration can overlap across nested events and is deliberately not
    described as wall-clock contribution or optimization benefit.
    """
    if capture.source_snapshot_id and capture.source_snapshot_id != snapshot.snapshot_id:
        raise ValueError("Profiler capture belongs to a different SceneSnapshot")
    selected_end = capture.duration_us if end_us is None else min(end_us, capture.duration_us)
    selected_start = max(0, min(start_us, selected_end))
    structural = build_root_cause_report(
        snapshot,
        focus_node_id,
        issues=issues,
        direction=direction,
        max_depth=max_depth,
        candidate_limit=max(candidate_limit * 4, candidate_limit),
    )
    stats = {stat.node_id: stat for stat in node_stats(capture, selected_start, selected_end)}
    selected_events = capture.events_in_range(selected_start, selected_end)
    mapped_event_count = sum(bool(event.node_id) for event in selected_events)
    measured = []
    for candidate in structural.candidates:
        stat = stats.get(candidate.node_id)
        path_duration = sum(
            stats[node_id].inclusive_duration_us
            for node_id in candidate.path_node_ids
            if node_id in stats
        )
        measured.append(
            MeasuredCandidate(
                structural=candidate,
                observed_inclusive_us=stat.inclusive_duration_us if stat else 0,
                observed_event_count=stat.event_count if stat else 0,
                observed_capture_share=stat.capture_share if stat else 0.0,
                path_inclusive_us=path_duration,
            )
        )
    measured.sort(
        key=lambda candidate: (
            -candidate.observed_inclusive_us,
            -candidate.path_inclusive_us,
            -candidate.structural.structural_score,
            candidate.structural.node_id,
        )
    )
    limited = tuple(measured[:candidate_limit])
    limited_structural = RootCauseReport(
        focus_node_id=structural.focus_node_id,
        direction=structural.direction,
        max_depth=structural.max_depth,
        scope_node_ids=structural.scope_node_ids,
        candidates=tuple(candidate.structural for candidate in limited),
        scanned_node_count=structural.scanned_node_count,
        truncated=structural.truncated,
    )
    return MeasuredRootCauseReport(
        structural=limited_structural,
        capture_id=capture.capture_id,
        selection_start_us=selected_start,
        selection_end_us=selected_end,
        candidates=limited,
        mapped_event_count=mapped_event_count,
        selected_event_count=len(selected_events),
    )
