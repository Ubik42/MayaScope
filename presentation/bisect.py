"""Host-independent presentation transitions for the Failure Prism."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable


@dataclass(frozen=True)
class BisectPrismState:
    mode: str = "隔离 / 串行 / 仅操作副本"
    signal: str = "已准备二分"
    detail: str = "尚未执行探针"
    outcome: str = ""
    candidate_count: int = 0
    active: bool = False
    cancel_visible: bool = True
    cancel_enabled: bool = True
    cancel_text: str = "本次探针后停止"
    resume_visible: bool = False
    dismiss_visible: bool = False


def begin_bisect_prism(plan) -> BisectPrismState:
    count = len(tuple(plan.candidates))
    isolation = str(plan.metadata.get("isolation_mode", "post-open-copy"))
    mode = {
        "post-open-copy": "打开后隔离",
        "pre-open-ascii": "打开前切片",
    }.get(isolation, isolation)
    return BisectPrismState(
        mode="%s  /  串行  /  仅操作副本" % mode,
        signal="%s 个候选已装载" % count,
        detail="源文件已锁定 · SHA %s" % str(plan.source_sha256)[:10],
        outcome="active",
        candidate_count=count,
        active=True,
    )


def present_bisect_attempt(state: BisectPrismState, step, attempt) -> BisectPrismState:
    outcome = str(attempt.outcome)
    signal = "%s  ·  %s / %s" % (
        {"pass": "通过", "fail": "复现", "unresolved": "未决"}.get(
            outcome, outcome
        ),
        len(tuple(step.candidate_ids)),
        state.candidate_count,
    )
    stage = {
        "confirm-source-failure": "确认源故障",
        "subset": "子集",
        "complement": "补集",
        "journal-replay": "日志重放",
    }.get(str(attempt.stage), str(attempt.stage))
    timeout = " · 超时" if attempt.timed_out else ""
    detail = "探针 %02d · %s · %.1f 秒%s" % (
        int(attempt.attempt_index) + 1,
        stage,
        float(attempt.duration_seconds),
        timeout,
    )
    return replace(state, signal=signal, detail=detail, outcome=outcome)


def request_bisect_cancel(state: BisectPrismState) -> BisectPrismState:
    return replace(
        state,
        cancel_enabled=False,
        cancel_text="已排队停止",
        detail="当前后台探针将安全完成后停止",
    )


def finish_bisect_prism(
    state: BisectPrismState,
    result,
    labels: Iterable[str],
) -> BisectPrismState:
    complete = bool(result.delta_debug.complete)
    reason = " + ".join(str(label) for label in labels) or "无最小原因集"
    return replace(
        state,
        signal="%s  ·  %s" % ("已隔离" if complete else "部分收敛", reason),
        detail="%s 次探针 · 复现胶囊 %s · SHA %s"
        % (
            len(tuple(result.manifest.attempts)),
            result.manifest_path.name,
            str(result.manifest_sha256)[:10],
        ),
        outcome="fail" if complete else "unresolved",
        active=False,
        cancel_visible=False,
        resume_visible=not complete,
        dismiss_visible=True,
    )


def fail_bisect_prism(state: BisectPrismState, message: str) -> BisectPrismState:
    return replace(
        state,
        signal="二分已停止",
        detail=str(message)[:110],
        outcome="unresolved",
        active=False,
        cancel_visible=False,
        resume_visible=True,
        dismiss_visible=True,
    )


__all__ = [
    "BisectPrismState",
    "begin_bisect_prism",
    "fail_bisect_prism",
    "finish_bisect_prism",
    "present_bisect_attempt",
    "request_bisect_cancel",
]
