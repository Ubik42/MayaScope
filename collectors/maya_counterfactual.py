"""Maya 2025 adapter for reversible nodeState counterfactual experiments."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Optional, Tuple

from ..analysis.counterfactual import (
    CounterfactualReport,
    ExperimentObservation,
    build_counterfactual_report,
)
from ..analysis.pulse import node_stats
from ..model import ProfilerCapture, SceneSnapshot
from .maya_profiler import profile_callable


class MayaCounterfactualError(RuntimeError):
    pass


@dataclass(frozen=True)
class NodeStateExperimentPlan:
    source_snapshot_id: str
    target_node_id: str
    target_name: str
    attribute: str
    baseline_value: int
    variant_value: int
    pair_count: int = 4
    warmup_count: int = 1

    def __post_init__(self) -> None:
        if self.pair_count < 2:
            raise ValueError("Counterfactual experiments require at least two pairs")
        if self.warmup_count < 0:
            raise ValueError("Counterfactual warmup count cannot be negative")
        if self.baseline_value == self.variant_value:
            raise ValueError("Counterfactual states must differ")

    def preview_lines(self) -> Tuple[str, ...]:
        return (
            "COUNTERFACTUAL PROFILER",
            "%s · %s" % (self.target_name, self.attribute),
            "baseline %s → temporary variant %s" % (self.baseline_value, self.variant_value),
            "%s paired trials · alternating AB / BA · %s warmup(s) per state"
            % (self.pair_count, self.warmup_count),
            "Undo recording is suspended; the original attribute and Undo head must be restored.",
        )


@dataclass(frozen=True)
class CounterfactualRun:
    report: CounterfactualReport
    baseline_captures: Tuple[ProfilerCapture, ...]
    variant_captures: Tuple[ProfilerCapture, ...]


def plan_node_state_experiment(
    snapshot: SceneSnapshot,
    node_id: str,
    *,
    pair_count: int = 4,
    warmup_count: int = 1,
    variant_value: int = 1,
) -> NodeStateExperimentPlan:
    node = snapshot.node_map.get(node_id)
    if node is None:
        raise MayaCounterfactualError("Counterfactual target is absent from the snapshot")
    if node.referenced:
        raise MayaCounterfactualError("Referenced nodes are protected from live experiments")
    name = node.dag_paths[0] if node.dag_paths else node.name
    return NodeStateExperimentPlan(
        source_snapshot_id=snapshot.snapshot_id,
        target_node_id=node.id,
        target_name=name,
        attribute="nodeState",
        baseline_value=0,
        variant_value=variant_value,
        pair_count=pair_count,
        warmup_count=warmup_count,
    )


class MayaNodeStateExperiment:
    """Run paired samples while guaranteeing temporary Maya state is restored."""

    def __init__(
        self,
        snapshot: SceneSnapshot,
        plan: NodeStateExperimentPlan,
        *,
        cmds_module: Any = None,
        operation: Optional[Callable[[], Any]] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
        buffer_size: int = 250_000,
    ):
        if cmds_module is None:
            try:
                import maya.cmds as cmds_module  # type: ignore
            except ImportError as exc:
                raise MayaCounterfactualError("Maya commands are unavailable") from exc
        self.cmds = cmds_module
        self.snapshot = snapshot
        self.plan = plan
        self.operation = operation or self._default_operation
        self.progress = progress
        self.buffer_size = buffer_size

    def _default_operation(self) -> None:
        self.cmds.dgdirty(allPlugs=True)
        self.cmds.refresh(force=True)

    def _validate(self) -> str:
        plan = self.plan
        if plan.source_snapshot_id != self.snapshot.snapshot_id:
            raise MayaCounterfactualError("Experiment plan belongs to a different SceneSnapshot")
        node = self.snapshot.node_map.get(plan.target_node_id)
        if node is None:
            raise MayaCounterfactualError("Experiment target no longer exists in the snapshot")
        if node.referenced:
            raise MayaCounterfactualError("Referenced nodes are protected from live experiments")
        name = plan.target_name
        if not self.cmds.objExists(name):
            raise MayaCounterfactualError("Experiment target no longer exists in Maya: %s" % name)
        identities = tuple(self.cmds.ls(name, uuid=True) or ())
        if identities and plan.target_node_id not in identities:
            raise MayaCounterfactualError("Experiment target identity changed after preview")
        if self.cmds.referenceQuery(name, isNodeReferenced=True):
            raise MayaCounterfactualError("Experiment target became referenced after preview")
        plug = "%s.%s" % (name, plan.attribute)
        if not self.cmds.objExists(plug):
            raise MayaCounterfactualError("Target has no supported nodeState adapter")
        if bool(self.cmds.getAttr(plug, lock=True)) or not bool(
            self.cmds.getAttr(plug, settable=True)
        ):
            raise MayaCounterfactualError("Target nodeState is locked or not settable")
        actual = int(self.cmds.getAttr(plug))
        if actual != plan.baseline_value:
            raise MayaCounterfactualError(
                "Experiment baseline changed after preview: expected %s, found %s"
                % (plan.baseline_value, actual)
            )
        return plug

    def _measure(self, pair_index: int, condition: str, order_index: int) -> Tuple[ExperimentObservation, ProfilerCapture]:
        elapsed = [0]

        def timed_operation():
            started = time.perf_counter_ns()
            try:
                return self.operation()
            finally:
                elapsed[0] = max(0, (time.perf_counter_ns() - started) // 1000)

        profiled = profile_callable(
            timed_operation,
            snapshot=self.snapshot,
            buffer_size=self.buffer_size,
            cmds_module=self.cmds,
        )
        capture = profiled.capture
        stats = node_stats(capture)
        return (
            ExperimentObservation(
                pair_index=pair_index,
                condition=condition,
                order_index=order_index,
                wall_time_us=elapsed[0],
                profiler_duration_us=capture.duration_us,
                mapped_event_count=capture.mapped_event_count,
                capture_id=capture.capture_id,
                node_inclusive_us=tuple(
                    (stat.node_id, stat.inclusive_duration_us) for stat in stats
                ),
            ),
            capture,
        )

    def run(self) -> CounterfactualRun:
        plug = self._validate()
        plan = self.plan
        undo_enabled = bool(self.cmds.undoInfo(query=True, state=True))
        undo_name = str(self.cmds.undoInfo(query=True, undoName=True) or "") if undo_enabled else ""
        observations = []
        captures = {"baseline": [], "variant": []}
        total = plan.pair_count * 2
        completed = 0
        failure = None
        restoration_failure = None
        if undo_enabled:
            self.cmds.undoInfo(stateWithoutFlush=False)
        try:
            for condition, value in (
                ("baseline", plan.baseline_value),
                ("variant", plan.variant_value),
            ):
                self.cmds.setAttr(plug, value)
                for _warmup in range(plan.warmup_count):
                    self.operation()
            for pair_index in range(plan.pair_count):
                order = (
                    ("baseline", "variant")
                    if pair_index % 2 == 0 else
                    ("variant", "baseline")
                )
                for order_index, condition in enumerate(order):
                    value = plan.baseline_value if condition == "baseline" else plan.variant_value
                    self.cmds.setAttr(plug, value)
                    observation, capture = self._measure(pair_index, condition, order_index)
                    observations.append(observation)
                    captures[condition].append(capture)
                    completed += 1
                    if self.progress:
                        self.progress(completed, total, condition)
        except Exception as exc:
            failure = exc
        finally:
            try:
                self.cmds.setAttr(plug, plan.baseline_value)
                restored = int(self.cmds.getAttr(plug))
                if restored != plan.baseline_value:
                    raise MayaCounterfactualError("Maya did not restore the original nodeState")
            except Exception as exc:
                restoration_failure = exc
            finally:
                if undo_enabled:
                    self.cmds.undoInfo(stateWithoutFlush=True)

        if restoration_failure is not None:
            raise MayaCounterfactualError(
                "CRITICAL: counterfactual state restoration failed: %s" % restoration_failure
            ) from restoration_failure
        if undo_enabled:
            current_undo_name = str(self.cmds.undoInfo(query=True, undoName=True) or "")
            if current_undo_name != undo_name:
                raise MayaCounterfactualError("Counterfactual experiment changed the Maya Undo head")
        if failure is not None:
            if isinstance(failure, MayaCounterfactualError):
                raise failure
            raise MayaCounterfactualError("Counterfactual sampling failed: %s" % failure) from failure

        report = build_counterfactual_report(
            observations,
            target_node_id=plan.target_node_id,
            target_name=plan.target_name,
            attribute=plan.attribute,
            baseline_value=plan.baseline_value,
            variant_value=plan.variant_value,
            source_snapshot_id=plan.source_snapshot_id,
            warmup_count=plan.warmup_count,
            metadata={
                "design": "paired alternating AB/BA",
                "outcome": "wall_time_us",
                "node_signal": "inclusive profiler duration; may overlap",
                "state_restored": True,
                "undo_head_preserved": True,
            },
        )
        return CounterfactualRun(
            report,
            tuple(captures["baseline"]),
            tuple(captures["variant"]),
        )
