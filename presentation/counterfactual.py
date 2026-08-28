"""Validated host-independent presentation for counterfactual experiments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Tuple

from ..analysis.counterfactual import CounterfactualReport


class CounterfactualPresentationError(ValueError):
    pass


@dataclass(frozen=True)
class CounterfactualPairState:
    pair_index: int
    baseline_us: float
    variant_us: float


@dataclass(frozen=True)
class CounterfactualViewState:
    target: str = "尚未实验"
    design: str = "成对 AB / BA 设计"
    metric: str = "—"
    interval: str = ""
    verdict: str = ""
    pairs: Tuple[CounterfactualPairState, ...] = ()
    heading: str = "反事实性能采样"
    body: str = ""
    action_text: str = "实验状态已恢复"
    status_text: str = ""


def empty_counterfactual() -> CounterfactualViewState:
    return CounterfactualViewState()


def _paired_observations(report: CounterfactualReport) -> Tuple[CounterfactualPairState, ...]:
    pairs = {}
    for observation in report.observations:
        bucket = pairs.setdefault(int(observation.pair_index), {})
        if observation.condition in bucket:
            raise CounterfactualPresentationError(
                "第 %s 组实验包含重复的 %s 样本。"
                % (observation.pair_index + 1, observation.condition)
            )
        bucket[observation.condition] = float(observation.wall_time_us)
    if not pairs:
        raise CounterfactualPresentationError("反事实报告没有成对实验样本。")
    if sorted(pairs) != list(range(len(pairs))):
        raise CounterfactualPresentationError("反事实实验 pair 序号不连续。")
    missing = [index for index, bucket in sorted(pairs.items()) if set(bucket) != {"baseline", "variant"}]
    if missing:
        raise CounterfactualPresentationError(
            "第 %s 组实验缺少 baseline 或 variant 样本。" % (missing[0] + 1)
        )
    return tuple(
        CounterfactualPairState(index, pairs[index]["baseline"], pairs[index]["variant"])
        for index in sorted(pairs)
    )


def present_counterfactual_report(
    report: CounterfactualReport,
    *,
    node_names: Mapping[str, str] | None = None,
    archive_path: str = "",
    archive_checksum: str = "",
) -> CounterfactualViewState:
    if not isinstance(report, CounterfactualReport):
        raise CounterfactualPresentationError("反事实结果类型无效。")
    pairs = _paired_observations(report)
    verdict_name = {
        "improved": "改善",
        "regressed": "变慢",
        "inconclusive": "证据不足",
    }[report.verdict]
    names = node_names or {}
    effects = []
    for rank, effect in enumerate(report.node_effects[:8], 1):
        effects.append(
            "%02d  %s  ·  实测包含耗时 Δ %+.3f ms"
            % (
                rank,
                names.get(effect.node_id, effect.node_id),
                effect.observed_delta_us / 1000.0,
            )
        )
    archive = "归档不可用；结果仍保留在当前调查会话中。"
    if archive_path:
        archive = "%s\nSHA-256 %s" % (Path(archive_path).name, archive_checksum)
    body = (
        "反事实实验 / NODESTATE\n"
        "%s  ·  %s %s → %s\n\n"
        "墙钟时间结果\n"
        "基线均值 %.3f ms · p95 %.3f ms\n"
        "变体均值 %.3f ms · p95 %.3f ms\n"
        "平均收益 %+.3f ms (%+.1f%%)\n"
        "成对 bootstrap 95%% 区间 %+.3f … %+.3f ms\n"
        "结论 %s · 实测噪声 %.1f%%\n\n"
        "试验设计\n"
        "%s 组成对试验 · AB / BA 交替 · 每种状态预热 %s 次\n"
        "结果为完整操作的墙钟时间；区间跨越零时视为证据不足。\n\n"
        "性能采样解释\n%s\n\n"
        "节点包含耗时可能重叠，不能直接相加为优化收益。\n\n"
        "恢复回执\n原始 nodeState 已恢复 · Maya Undo 顶部已保留\n\n"
        "证据归档\n%s"
        % (
            report.target_name or report.target_node_id,
            report.attribute,
            report.baseline_value,
            report.variant_value,
            report.baseline_mean_us / 1000.0,
            report.baseline_p95_us / 1000.0,
            report.variant_mean_us / 1000.0,
            report.variant_p95_us / 1000.0,
            report.benefit_mean_us / 1000.0,
            report.benefit_percent,
            report.benefit_ci_low_us / 1000.0,
            report.benefit_ci_high_us / 1000.0,
            verdict_name,
            report.noise_ratio * 100.0,
            len(pairs),
            report.warmup_count,
            "\n".join(effects) if effects else "没有可唯一映射的节点事件。",
            archive,
        )
    )
    return CounterfactualViewState(
        target=report.target_name or report.target_node_id,
        design="%s 组配对 · %s 次预热 · 状态已恢复"
        % (len(pairs), report.warmup_count),
        metric="%s  ·  %+.1f%%" % (verdict_name, report.benefit_percent),
        interval="95%% 区间  %+.1f%% … %+.1f%%  ·  墙钟时间"
        % (report.benefit_ci_low_percent, report.benefit_ci_high_percent),
        verdict=report.verdict,
        pairs=pairs,
        body=body,
        status_text="反事实实验：%s  ·  %+.1f%%  ·  状态与 Undo 已恢复"
        % (verdict_name, report.benefit_percent),
    )


__all__ = [
    "CounterfactualPairState",
    "CounterfactualPresentationError",
    "CounterfactualViewState",
    "empty_counterfactual",
    "present_counterfactual_report",
]
