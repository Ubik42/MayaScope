"""Bounded Maya evaluation wall-clock sampling for regression evidence."""

from __future__ import annotations

from time import perf_counter_ns
from typing import Any, Dict

from ..analysis.regression import summarize_performance


def collect_evaluation_performance(
    *,
    sample_count: int = 7,
    warmup_count: int = 2,
    cmds_module: Any = None,
) -> Dict[str, Any]:
    if sample_count < 3 or sample_count > 101:
        raise ValueError("sample_count must be between 3 and 101")
    if warmup_count < 0 or warmup_count > 20:
        raise ValueError("warmup_count must be between 0 and 20")
    if cmds_module is None:
        import maya.cmds as cmds_module  # type: ignore

    original_time = float(cmds_module.currentTime(query=True))
    minimum = float(cmds_module.playbackOptions(query=True, minTime=True))
    maximum = float(cmds_module.playbackOptions(query=True, maxTime=True))
    alternate_time = original_time + 1.0
    if alternate_time > maximum:
        alternate_time = original_time - 1.0
    if alternate_time < minimum or alternate_time == original_time:
        alternate_time = minimum if minimum != original_time else maximum
    if alternate_time == original_time:
        raise RuntimeError("Playback range has no alternate evaluation sample")

    ordinal = 0
    geometry = tuple(cmds_module.ls(geometry=True, long=True) or ())
    transforms = tuple(cmds_module.ls(type="transform", long=True) or ())

    def pull_outputs():
        if geometry:
            cmds_module.exactWorldBoundingBox(list(geometry), ignoreInvisible=False)
        elif transforms:
            for node in transforms:
                cmds_module.getAttr(node + ".worldMatrix[0]")

    def evaluate_once() -> int:
        nonlocal ordinal
        target = alternate_time if ordinal % 2 == 0 else original_time
        ordinal += 1
        cmds_module.dgdirty(allPlugs=True)
        started = perf_counter_ns()
        cmds_module.currentTime(target, edit=True, update=False)
        pull_outputs()
        return max(0, (perf_counter_ns() - started) // 1000)

    try:
        for _ in range(warmup_count):
            evaluate_once()
        samples = tuple(evaluate_once() for _ in range(sample_count))
    finally:
        cmds_module.currentTime(original_time, edit=True, update=False)
        pull_outputs()
    summary = summarize_performance(samples)
    mode = cmds_module.evaluationManager(query=True, mode=True)
    if isinstance(mode, (tuple, list)):
        mode = ",".join(str(item) for item in mode)
    return {
        "operation": "dgdirty-all-plugs + alternating-time demand-driven output pull",
        "sample_count": sample_count,
        "warmup_count": warmup_count,
        "samples_us": samples,
        "median_us": summary.median_us,
        "p95_us": summary.p95_us,
        "mad_us": summary.mad_us,
        "noise_ratio": summary.noise_ratio,
        "evaluation_mode": str(mode or "unknown"),
        "original_time": original_time,
        "alternate_time": alternate_time,
        "time_restored": float(cmds_module.currentTime(query=True)) == original_time,
        "geometry_target_count": len(geometry),
        "transform_fallback_count": 0 if geometry else len(transforms),
        "time_unit": "microseconds",
    }
