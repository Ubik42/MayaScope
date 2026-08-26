"""Extensible, fault-isolated rule execution for the Scene Clinic."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from .rules import (
    CrossReferenceConnectionRule,
    CycleRule,
    HighFanoutRule,
    Issue,
    NamespaceDepthRule,
    NestedReferenceDepthRule,
    OrphanUtilityRule,
    OrphanAnimationCurveRule,
    Rule,
    RuntimeScriptNodeRule,
    MissingExternalDependencyRule,
    ExternalSequenceGapRule,
    MissingPluginRequirementRule,
    MissingReferenceFileRule,
    NonPortableExternalDependencyRule,
    ReferenceNamespaceIntrusionRule,
    UnloadedReferenceRule,
    UnknownNodeRule,
    UnsavedSceneRule,
    UnsavedSceneChangesRule,
    FailedReferenceEditRule,
)
from ..model import SceneSnapshot


VALID_CATEGORIES = frozenset({"integrity", "performance", "references", "pipeline"})
VALID_CONFIDENCE = frozenset({"deterministic", "strong", "heuristic"})
VALID_COST = frozenset({"instant", "moderate", "expensive"})


class ClinicCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class RuleProfile:
    id: str
    title: str
    description: str
    rule_ids: Tuple[str, ...]
    include_expensive: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_ids", tuple(self.rule_ids))
        if not self.id or not self.title or not self.rule_ids:
            raise ValueError("RuleProfile id, title, and rule_ids are required")


@dataclass(frozen=True)
class RuleSpec:
    rule: Rule
    title: str
    category: str
    confidence: str
    cost: str = "instant"
    default_enabled: bool = True
    repair_kind: str = "diagnostic"

    @property
    def id(self) -> str:
        return self.rule.id

    def __post_init__(self) -> None:
        if not self.id or not self.title:
            raise ValueError("RuleSpec id and title are required")
        if self.category not in VALID_CATEGORIES:
            raise ValueError("Unsupported rule category: %s" % self.category)
        if self.confidence not in VALID_CONFIDENCE:
            raise ValueError("Unsupported rule confidence: %s" % self.confidence)
        if self.cost not in VALID_COST:
            raise ValueError("Unsupported rule cost: %s" % self.cost)


@dataclass(frozen=True)
class RuleRun:
    rule_id: str
    duration_ms: float
    issue_count: int


@dataclass(frozen=True)
class RuleFailure:
    rule_id: str
    message: str


@dataclass(frozen=True)
class ClinicReport:
    snapshot_id: str
    issues: Tuple[Issue, ...]
    runs: Tuple[RuleRun, ...]
    failures: Tuple[RuleFailure, ...]
    skipped_rule_ids: Tuple[str, ...]

    @property
    def duration_ms(self) -> float:
        return sum(run.duration_ms for run in self.runs)


class RuleRegistry:
    """Ordered rule catalog with validation and per-rule failure isolation."""

    def __init__(self, specs: Iterable[RuleSpec] = ()):
        self._specs: Dict[str, RuleSpec] = {}
        for spec in specs:
            self.register(spec)

    @property
    def specs(self) -> Tuple[RuleSpec, ...]:
        return tuple(self._specs.values())

    def register(self, spec: RuleSpec) -> None:
        if spec.id in self._specs:
            raise ValueError("Duplicate rule id: %s" % spec.id)
        self._specs[spec.id] = spec

    def evaluate(
        self,
        snapshot: SceneSnapshot,
        enabled_rule_ids: Optional[Sequence[str]] = None,
        include_expensive: bool = False,
        cancelled: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> ClinicReport:
        enabled = set(enabled_rule_ids) if enabled_rule_ids is not None else {
            spec.id for spec in self.specs if spec.default_enabled
        }
        unknown = enabled.difference(self._specs)
        if unknown:
            raise ValueError("Unknown rule id: %s" % sorted(unknown)[0])
        issues = []
        runs = []
        failures = []
        skipped = []
        known_nodes = set(snapshot.node_map)
        seen_issue_ids = set()
        runnable = tuple(
            spec for spec in self.specs
            if spec.id in enabled and not (spec.cost == "expensive" and not include_expensive)
        )
        completed = 0
        for spec in self.specs:
            if spec.id not in enabled or (spec.cost == "expensive" and not include_expensive):
                skipped.append(spec.id)
                continue
            if cancelled and cancelled():
                raise ClinicCancelled("Scene Clinic cancelled between rules")
            started = perf_counter()
            try:
                produced = tuple(spec.rule.evaluate(snapshot))
                for issue in produced:
                    if issue.rule_id != spec.id:
                        raise ValueError("issue rule_id does not match its registered rule")
                    if issue.id in seen_issue_ids:
                        raise ValueError("duplicate issue id: %s" % issue.id)
                    missing = set(issue.affected_node_ids).difference(known_nodes)
                    if missing:
                        raise ValueError("issue references missing node: %s" % sorted(missing)[0])
                    missing_subject_nodes = {
                        node_id
                        for _subject, node_id in issue.atomic_subjects
                        if node_id and node_id not in known_nodes
                    }
                    if missing_subject_nodes:
                        raise ValueError(
                            "issue atomic subject references missing node: %s"
                            % sorted(missing_subject_nodes)[0]
                        )
                    seen_issue_ids.add(issue.id)
                issues.extend(produced)
                runs.append(RuleRun(spec.id, (perf_counter() - started) * 1000.0, len(produced)))
            except Exception as exc:
                failures.append(RuleFailure(spec.id, "%s: %s" % (type(exc).__name__, exc)))
            completed += 1
            if progress:
                progress(completed, len(runnable), spec.id)
        issues.sort(key=lambda issue: (-int(issue.severity), issue.title, issue.id))
        return ClinicReport(snapshot.snapshot_id, tuple(issues), tuple(runs), tuple(failures), tuple(skipped))


DEFAULT_REGISTRY = RuleRegistry(
    (
        RuleSpec(MissingPluginRequirementRule(), "缺失插件依赖", "pipeline", "deterministic"),
        RuleSpec(UnknownNodeRule(), "未知节点残留", "integrity", "deterministic", repair_kind="previewed"),
        RuleSpec(CycleRule(), "DG 依赖循环", "integrity", "deterministic"),
        RuleSpec(HighFanoutRule(), "高扇出热点", "performance", "heuristic"),
        RuleSpec(CrossReferenceConnectionRule(), "跨引用耦合", "references", "strong"),
        RuleSpec(OrphanUtilityRule(), "游离工具节点", "performance", "heuristic"),
        RuleSpec(NamespaceDepthRule(), "命名空间过深", "pipeline", "strong"),
        RuleSpec(MissingReferenceFileRule(), "引用源文件缺失", "references", "deterministic"),
        RuleSpec(ReferenceNamespaceIntrusionRule(), "引用命名空间越界", "references", "deterministic"),
        RuleSpec(UnloadedReferenceRule(), "未加载引用", "references", "deterministic"),
        RuleSpec(FailedReferenceEditRule(), "引用编辑失败", "references", "deterministic"),
        RuleSpec(NestedReferenceDepthRule(), "引用嵌套深度", "references", "strong"),
        RuleSpec(UnsavedSceneRule(), "未保存场景身份", "pipeline", "deterministic"),
        RuleSpec(UnsavedSceneChangesRule(), "场景存在未保存修改", "pipeline", "deterministic"),
        RuleSpec(RuntimeScriptNodeRule(), "运行时脚本节点", "pipeline", "strong"),
        RuleSpec(OrphanAnimationCurveRule(), "游离动画曲线", "performance", "heuristic"),
        RuleSpec(MissingExternalDependencyRule(), "外部文件依赖缺失", "pipeline", "deterministic"),
        RuleSpec(NonPortableExternalDependencyRule(), "外部依赖不可移植", "pipeline", "strong"),
        RuleSpec(ExternalSequenceGapRule(), "缓存与序列缺帧", "pipeline", "strong"),
    )
)


DEFAULT_PROFILES = (
    RuleProfile("all", "全量信号", "启用所有默认诊所规则。", tuple(spec.id for spec in DEFAULT_REGISTRY.specs)),
    RuleProfile("rig", "绑定手术", "聚焦图完整性、工具节点残留与引用边界。", ("missing-plugin-requirements", "unknown-nodes", "dg-cycles", "high-fanout", "cross-reference-links", "orphan-utilities", "missing-reference-files", "reference-namespace-intrusion", "unloaded-references", "failed-reference-edits", "nested-reference-depth")),
    RuleProfile("animation", "动画脉冲", "聚焦影响交互播放的求值风险与图残留。", ("missing-plugin-requirements", "dg-cycles", "high-fanout", "orphan-utilities", "orphan-animation-curves", "runtime-script-nodes", "external-sequence-gaps")),
    RuleProfile("publish", "发布入口", "聚焦序列化、内存状态、场景组合、外部依赖与命名边界风险。", ("missing-plugin-requirements", "unknown-nodes", "dg-cycles", "cross-reference-links", "namespace-depth", "missing-reference-files", "reference-namespace-intrusion", "unloaded-references", "failed-reference-edits", "nested-reference-depth", "unsaved-scene", "unsaved-scene-changes", "runtime-script-nodes", "missing-external-files", "nonportable-external-files", "external-sequence-gaps")),
)


def profile_map(
    profiles: Sequence[RuleProfile] = DEFAULT_PROFILES,
    registry: RuleRegistry = DEFAULT_REGISTRY,
) -> Dict[str, RuleProfile]:
    result = {}
    known = {spec.id for spec in registry.specs}
    for profile in profiles:
        if profile.id in result:
            raise ValueError("Duplicate profile id: %s" % profile.id)
        missing = set(profile.rule_ids).difference(known)
        if missing:
            raise ValueError("Profile references unknown rule: %s" % sorted(missing)[0])
        result[profile.id] = profile
    return result
