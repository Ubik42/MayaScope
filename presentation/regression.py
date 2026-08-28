"""Validated host-independent presentation for signed regression reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple


class RegressionPresentationError(ValueError):
    pass


@dataclass(frozen=True)
class RegressionPerformanceState:
    comparable: bool = False
    regressed: bool = False
    baseline_samples_us: Tuple[float, ...] = ()
    current_samples_us: Tuple[float, ...] = ()
    baseline_median_us: float = 0.0
    current_median_us: float = 0.0
    required_delta_us: float = 0.0
    delta_us: float = 0.0
    slowdown_ratio: float = 0.0


@dataclass(frozen=True)
class RegressionRiftState:
    verdict: str = "尚无证据"
    detail: str = ""
    identity: str = "签名基线"
    failed: bool = False
    performance: RegressionPerformanceState = RegressionPerformanceState()
    active_node_ids: Tuple[str, ...] = ()
    evidence_body: str = ""
    status_text: str = ""


def empty_regression_rift() -> RegressionRiftState:
    return RegressionRiftState()


def _performance_state(payload) -> RegressionPerformanceState:
    if not isinstance(payload, Mapping) or not payload.get("comparable"):
        return RegressionPerformanceState()
    baseline = payload.get("baseline")
    current = payload.get("current")
    if not isinstance(baseline, Mapping) or not isinstance(current, Mapping):
        raise RegressionPresentationError("性能配对证据缺少基线或当前样本摘要。")
    try:
        before_samples = tuple(float(value) for value in baseline["samples_us"])
        after_samples = tuple(float(value) for value in current["samples_us"])
        if not before_samples or not after_samples:
            raise ValueError("empty samples")
        return RegressionPerformanceState(
            comparable=True,
            regressed=bool(payload.get("regressed")),
            baseline_samples_us=before_samples,
            current_samples_us=after_samples,
            baseline_median_us=float(baseline["median_us"]),
            current_median_us=float(current["median_us"]),
            required_delta_us=float(payload["required_delta_us"]),
            delta_us=float(payload["delta_us"]),
            slowdown_ratio=float(payload["slowdown_ratio"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RegressionPresentationError("性能配对证据字段不完整，回归结果未呈现。") from exc


def _finding_group(regression: Mapping, name: str) -> Tuple[Mapping, ...]:
    value = regression.get(name, ())
    if isinstance(value, (str, bytes)):
        raise RegressionPresentationError("回归发现列表格式无效：%s" % name)
    try:
        items = tuple(value)
    except TypeError as exc:
        raise RegressionPresentationError("回归发现列表格式无效：%s" % name) from exc
    if any(not isinstance(item, Mapping) for item in items):
        raise RegressionPresentationError("回归发现必须是结构化记录：%s" % name)
    return items


def present_regression_report(payload) -> RegressionRiftState:
    if not isinstance(payload, Mapping):
        raise RegressionPresentationError("回归报告必须是结构化对象。")
    regression = payload.get("regression")
    if not isinstance(regression, Mapping):
        raise RegressionPresentationError("报告缺少经过验证的 regression 结果。")

    new = _finding_group(regression, "new_findings")
    escalated = _finding_group(regression, "escalated_findings")
    resolved = _finding_group(regression, "resolved_findings")
    performance = _performance_state(regression.get("performance", {}))
    failed = bool(regression.get("gate_failed"))
    perf_short = "无性能配对"
    perf_body = "性能证据不可用。"
    if performance.comparable:
        perf_short = "%+.2f ms  ·  %+.1f%%" % (
            performance.delta_us / 1000.0,
            performance.slowdown_ratio * 100.0,
        )
        perf_body = (
            "求值中位数：%.2f → %.2f ms\n触发门槛：%.2f ms\n"
            "实测变化：%+.2f ms (%+.1f%%)"
            % (
                performance.baseline_median_us / 1000.0,
                performance.current_median_us / 1000.0,
                performance.required_delta_us / 1000.0,
                performance.delta_us / 1000.0,
                performance.slowdown_ratio * 100.0,
            )
        )

    active = []
    seen = set()
    for item in new + escalated:
        node_id = str(item.get("node_id", ""))
        if node_id not in {"", "<scene>"} and node_id not in seen:
            seen.add(node_id)
            active.append(node_id)
    verdict = "检测到回归裂隙" if failed else "基线保持稳定"
    baseline_sha = str(regression.get("baseline_report_sha256", ""))
    current_sha = str(payload.get("report_sha256", ""))
    return RegressionRiftState(
        verdict=verdict,
        detail="新增 %s · 升级 %s · 已解决 %s · %s"
        % (len(new), len(escalated), len(resolved), perf_short),
        identity="基线 %s / 当前 %s"
        % (baseline_sha[:8].upper(), current_sha[:8].upper()),
        failed=failed,
        performance=performance,
        active_node_ids=tuple(active),
        evidence_body="签名回归证据\n%s\n\n新增：%s · 升级：%s · 已解决：%s\n%s"
        % (verdict, len(new), len(escalated), len(resolved), perf_body),
        status_text="回归裂隙  ·  %s" % ("门禁失败" if failed else "基线保持稳定"),
    )


__all__ = [
    "RegressionPerformanceState",
    "RegressionPresentationError",
    "RegressionRiftState",
    "empty_regression_rift",
    "present_regression_report",
]
