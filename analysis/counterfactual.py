"""Host-independent paired counterfactual experiment statistics.

The total operation wall time is the causal outcome. Profiler node durations are
retained as explanatory, inclusive signals only; nested events may overlap.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import random
import statistics
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple
from uuid import uuid4


COUNTERFACTUAL_SCHEMA_VERSION = 1
CONDITIONS = frozenset({"baseline", "variant"})


@dataclass(frozen=True)
class ExperimentObservation:
    pair_index: int
    condition: str
    order_index: int
    wall_time_us: int
    profiler_duration_us: int
    mapped_event_count: int
    capture_id: str = ""
    node_inclusive_us: Tuple[Tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if self.pair_index < 0 or self.order_index not in {0, 1}:
            raise ValueError("Invalid counterfactual pair position")
        if self.condition not in CONDITIONS:
            raise ValueError("Unknown counterfactual condition: %s" % self.condition)
        if min(self.wall_time_us, self.profiler_duration_us, self.mapped_event_count) < 0:
            raise ValueError("Counterfactual measurements cannot be negative")
        normalized = tuple((str(node_id), int(duration)) for node_id, duration in self.node_inclusive_us)
        if any(not node_id or duration < 0 for node_id, duration in normalized):
            raise ValueError("Invalid node-inclusive measurement")
        if len({node_id for node_id, _duration in normalized}) != len(normalized):
            raise ValueError("Duplicate node-inclusive measurement")
        object.__setattr__(self, "node_inclusive_us", normalized)


@dataclass(frozen=True)
class NodeExperimentEffect:
    node_id: str
    baseline_mean_us: float
    variant_mean_us: float
    observed_delta_us: float


@dataclass(frozen=True)
class CounterfactualReport:
    target_node_id: str
    target_name: str
    attribute: str
    baseline_value: int
    variant_value: int
    observations: Tuple[ExperimentObservation, ...]
    baseline_mean_us: float
    variant_mean_us: float
    baseline_p95_us: float
    variant_p95_us: float
    benefit_mean_us: float
    benefit_ci_low_us: float
    benefit_ci_high_us: float
    benefit_percent: float
    benefit_ci_low_percent: float
    benefit_ci_high_percent: float
    noise_ratio: float
    verdict: str
    node_effects: Tuple[NodeExperimentEffect, ...] = ()
    source_snapshot_id: str = ""
    warmup_count: int = 0
    experiment_id: str = field(default_factory=lambda: "experiment-%s" % uuid4().hex[:12])
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = COUNTERFACTUAL_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "node_effects", tuple(self.node_effects))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.verdict not in {"improved", "inconclusive", "regressed"}:
            raise ValueError("Invalid counterfactual verdict")

    @property
    def pair_count(self) -> int:
        return len(self.observations) // 2

    def condition_values(self, condition: str) -> Tuple[int, ...]:
        return tuple(item.wall_time_us for item in self.observations if item.condition == condition)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CounterfactualReport":
        version = int(payload.get("schema_version", 0))
        if version != COUNTERFACTUAL_SCHEMA_VERSION:
            raise ValueError("Unsupported CounterfactualReport schema: %s" % version)
        values = dict(payload)
        values["observations"] = tuple(
            ExperimentObservation(
                **{
                    **item,
                    "node_inclusive_us": tuple(tuple(value) for value in item.get("node_inclusive_us", ())),
                }
            )
            for item in payload.get("observations", ())
        )
        values["node_effects"] = tuple(
            NodeExperimentEffect(**item) for item in payload.get("node_effects", ())
        )
        return cls(**values)

    @classmethod
    def from_json(cls, value: str) -> "CounterfactualReport":
        return cls.from_dict(json.loads(value))


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _coefficient_of_variation(values: Sequence[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    return statistics.stdev(values) / mean if mean else 0.0


def _bootstrap_mean_interval(
    paired_differences: Sequence[int], iterations: int, seed: int
) -> Tuple[float, float]:
    if not paired_differences:
        raise ValueError("At least one paired difference is required")
    if iterations < 100:
        raise ValueError("At least 100 bootstrap iterations are required")
    if len(paired_differences) == 1:
        value = float(paired_differences[0])
        return value, value
    generator = random.Random(seed)
    count = len(paired_differences)
    means = [
        statistics.fmean(
            paired_differences[generator.randrange(count)] for _index in range(count)
        )
        for _iteration in range(iterations)
    ]
    return _percentile(means, 0.025), _percentile(means, 0.975)


def _node_effects(observations: Sequence[ExperimentObservation]) -> Tuple[NodeExperimentEffect, ...]:
    by_condition: Dict[str, Dict[str, list]] = {
        "baseline": {},
        "variant": {},
    }
    for observation in observations:
        for node_id, duration in observation.node_inclusive_us:
            by_condition[observation.condition].setdefault(node_id, []).append(duration)
    effects = []
    node_ids = set(by_condition["baseline"]) | set(by_condition["variant"])
    for node_id in node_ids:
        baseline = statistics.fmean(by_condition["baseline"].get(node_id, (0,)))
        variant = statistics.fmean(by_condition["variant"].get(node_id, (0,)))
        effects.append(NodeExperimentEffect(node_id, baseline, variant, baseline - variant))
    return tuple(sorted(effects, key=lambda item: (-abs(item.observed_delta_us), item.node_id)))


def build_counterfactual_report(
    observations: Iterable[ExperimentObservation],
    *,
    target_node_id: str,
    target_name: str,
    attribute: str,
    baseline_value: int,
    variant_value: int,
    source_snapshot_id: str = "",
    warmup_count: int = 0,
    bootstrap_iterations: int = 4000,
    bootstrap_seed: int = 0x5C0FE,
    metadata: Mapping[str, Any] | None = None,
) -> CounterfactualReport:
    """Compare paired AB/BA observations without claiming node time is additive."""
    measured = tuple(observations)
    if not measured:
        raise ValueError("Counterfactual observations are required")
    pairs: Dict[int, Dict[str, ExperimentObservation]] = {}
    for item in measured:
        condition_map = pairs.setdefault(item.pair_index, {})
        if item.condition in condition_map:
            raise ValueError("Duplicate %s observation in pair %s" % (item.condition, item.pair_index))
        condition_map[item.condition] = item
    if any(set(condition_map) != CONDITIONS for condition_map in pairs.values()):
        raise ValueError("Every counterfactual pair requires baseline and variant observations")
    if sorted(pairs) != list(range(len(pairs))):
        raise ValueError("Counterfactual pair indexes must be contiguous")

    baseline = tuple(pairs[index]["baseline"].wall_time_us for index in sorted(pairs))
    variant = tuple(pairs[index]["variant"].wall_time_us for index in sorted(pairs))
    differences = tuple(before - after for before, after in zip(baseline, variant))
    baseline_mean = statistics.fmean(baseline)
    variant_mean = statistics.fmean(variant)
    benefit = statistics.fmean(differences)
    low, high = _bootstrap_mean_interval(differences, bootstrap_iterations, bootstrap_seed)
    divisor = baseline_mean or 1.0
    if low > 0:
        verdict = "improved"
    elif high < 0:
        verdict = "regressed"
    else:
        verdict = "inconclusive"
    return CounterfactualReport(
        target_node_id=target_node_id,
        target_name=target_name,
        attribute=attribute,
        baseline_value=baseline_value,
        variant_value=variant_value,
        observations=measured,
        baseline_mean_us=baseline_mean,
        variant_mean_us=variant_mean,
        baseline_p95_us=_percentile(baseline, 0.95),
        variant_p95_us=_percentile(variant, 0.95),
        benefit_mean_us=benefit,
        benefit_ci_low_us=low,
        benefit_ci_high_us=high,
        benefit_percent=benefit / divisor * 100.0,
        benefit_ci_low_percent=low / divisor * 100.0,
        benefit_ci_high_percent=high / divisor * 100.0,
        noise_ratio=max(_coefficient_of_variation(baseline), _coefficient_of_variation(variant)),
        verdict=verdict,
        node_effects=_node_effects(measured),
        source_snapshot_id=source_snapshot_id,
        warmup_count=warmup_count,
        metadata=dict(metadata or {}),
    )
