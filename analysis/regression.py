"""Evidence-first comparison of Scene Clinic audit reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import statistics
from typing import Any, Dict, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class PerformanceSummary:
    samples_us: Tuple[int, ...]
    median_us: float
    p95_us: float
    mad_us: float
    noise_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def summarize_performance(samples_us: Sequence[int]) -> PerformanceSummary:
    samples = tuple(int(value) for value in samples_us)
    if len(samples) < 3:
        raise ValueError("Performance evidence requires at least three samples")
    if any(value < 0 for value in samples):
        raise ValueError("Performance samples must be non-negative")
    ordered = sorted(samples)
    median = float(statistics.median(ordered))
    rank = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))
    p95 = float(ordered[rank])
    mad = float(statistics.median(abs(value - median) for value in ordered))
    return PerformanceSummary(samples, median, p95, mad, mad / (median or 1.0))


def _atomic_findings(payload: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for issue in payload.get("issues", ()):
        rule_id = str(issue.get("rule_id", ""))
        affected = tuple(str(item) for item in issue.get("affected_node_ids", ()))
        subjects = tuple(
            (str(item.get("id", "")), str(item.get("node_id", "")))
            for item in issue.get("atomic_subjects", ())
            if isinstance(item, dict) and item.get("id")
        )
        if not subjects:
            subjects = tuple((node_id, node_id) for node_id in affected)
        if not subjects:
            subject = str(issue.get("id", "")) or "<scene>"
            subjects = ((subject, ""),)
        for subject_id, owner_node_id in subjects:
            key = "%s|%s" % (rule_id, subject_id)
            candidate = {
                "key": key,
                "rule_id": rule_id,
                "subject_id": subject_id,
                "node_id": owner_node_id or "<scene>",
                "severity": str(issue.get("severity", "")),
                "severity_value": int(issue.get("severity_value", 0)),
                "title": str(issue.get("title", rule_id)),
            }
            previous = result.get(key)
            if previous is None or candidate["severity_value"] > previous["severity_value"]:
                result[key] = candidate
    return result


def compare_audit_reports(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    severity_threshold: int = 30,
    max_slowdown_ratio: float = 0.20,
    min_slowdown_us: int = 2000,
) -> Dict[str, Any]:
    """Compare signed audit payloads without treating nested Profiler events as additive."""
    for label, payload in (("baseline", baseline), ("current", current)):
        if payload.get("format") != "mayascope.clinic-audit":
            raise ValueError("%s is not a Scene Clinic audit" % label.title())
    if baseline.get("profile") != current.get("profile"):
        raise ValueError("Audit profiles differ")
    if baseline.get("config_fingerprint") != current.get("config_fingerprint"):
        raise ValueError("Clinic configuration fingerprints differ")
    if baseline.get("maya", {}).get("version") != current.get("maya", {}).get("version"):
        raise ValueError("Maya versions differ")
    before_snapshot = baseline.get("snapshot", {})
    after_snapshot = current.get("snapshot", {})
    before_lifecycle = before_snapshot.get("scene_lifecycle", {})
    after_lifecycle = after_snapshot.get("scene_lifecycle", {})
    before_workspace = str(before_lifecycle.get("workspace_root", ""))
    after_workspace = str(after_lifecycle.get("workspace_root", ""))
    if before_workspace and after_workspace and os.path.normcase(os.path.normpath(before_workspace)) != os.path.normcase(os.path.normpath(after_workspace)):
        raise ValueError("Audit workspaces differ")
    before_settings = before_snapshot.get("scene_settings", {})
    after_settings = after_snapshot.get("scene_settings", {})
    comparable_setting_fields = (
        "time_unit", "linear_unit", "angular_unit", "up_axis",
        "color_management_enabled", "rendering_space",
    )
    if before_settings and after_settings and any(
        before_settings.get(field) != after_settings.get(field)
        for field in comparable_setting_fields
    ):
        raise ValueError("Audit scene settings differ")
    if max_slowdown_ratio < 0 or min_slowdown_us < 0:
        raise ValueError("Performance regression thresholds must be non-negative")

    before = _atomic_findings(baseline)
    after = _atomic_findings(current)
    new = tuple(after[key] for key in sorted(set(after).difference(before)))
    resolved = tuple(before[key] for key in sorted(set(before).difference(after)))
    escalated = tuple(
        dict(after[key], baseline_severity=before[key]["severity"])
        for key in sorted(set(before).intersection(after))
        if after[key]["severity_value"] > before[key]["severity_value"]
    )
    clinic_gate = any(
        item["severity_value"] >= severity_threshold for item in new + escalated
    )

    performance = {
        "comparable": False,
        "regressed": False,
        "reason": "Performance samples are missing from one or both reports",
    }
    before_perf = baseline.get("performance")
    after_perf = current.get("performance")
    if before_perf and after_perf:
        if before_perf.get("evaluation_mode") != after_perf.get("evaluation_mode"):
            raise ValueError("Maya evaluation modes differ")
        before_summary = summarize_performance(before_perf.get("samples_us", ()))
        after_summary = summarize_performance(after_perf.get("samples_us", ()))
        delta = after_summary.median_us - before_summary.median_us
        threshold = max(
            float(min_slowdown_us),
            before_summary.median_us * float(max_slowdown_ratio),
            3.0 * (before_summary.mad_us + after_summary.mad_us),
        )
        performance = {
            "comparable": True,
            "regressed": delta > threshold,
            "reason": "Median slowdown exceeds the configured and observed noise bands" if delta > threshold else "Within configured or observed noise bands",
            "baseline": before_summary.to_dict(),
            "current": after_summary.to_dict(),
            "delta_us": delta,
            "slowdown_ratio": delta / (before_summary.median_us or 1.0),
            "required_delta_us": threshold,
            "max_slowdown_ratio": float(max_slowdown_ratio),
            "min_slowdown_us": int(min_slowdown_us),
            "evaluation_mode": after_perf.get("evaluation_mode"),
        }

    snapshot_delta = {
        key: int(after_snapshot.get(key, 0)) - int(before_snapshot.get(key, 0))
        for key in ("nodes", "edges", "references")
    }
    snapshot_delta["external_dependencies"] = len(
        after_snapshot.get("external_dependencies", ())
    ) - len(before_snapshot.get("external_dependencies", ()))
    return {
        "format": "mayascope.audit-regression",
        "schema_version": 1,
        "baseline_report_sha256": baseline.get("report_sha256", ""),
        "new_findings": new,
        "escalated_findings": escalated,
        "resolved_findings": resolved,
        "snapshot_delta": snapshot_delta,
        "performance": performance,
        "clinic_gate_failed": clinic_gate,
        "performance_gate_failed": bool(performance["regressed"]),
        "gate_failed": clinic_gate or bool(performance["regressed"]),
    }
