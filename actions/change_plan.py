"""Explicit preview/execute boundary for Maya scene changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence, Tuple
from uuid import uuid4

from ..analysis.rules import Issue
from ..model import SceneSnapshot


@dataclass(frozen=True)
class ChangeStep:
    operation: str
    node_ids: Tuple[str, ...]
    node_names: Tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ChangePlan:
    id: str
    title: str
    issue_id: str
    steps: Tuple[ChangeStep, ...]
    destructive: bool = False
    issue_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "issue_ids",
            tuple(self.issue_ids) or ((self.issue_id,) if self.issue_id else ()),
        )

    @property
    def affected_count(self) -> int:
        return sum(len(step.node_ids) for step in self.steps)

    def preview_lines(self) -> Tuple[str, ...]:
        lines = [
            self.title,
            "%s 项发现 · 影响 %s 个节点"
            % (len(self.issue_ids), self.affected_count),
        ]
        for step in self.steps:
            operation = {"delete_nodes": "删除节点"}.get(step.operation, step.operation)
            lines.append("%s：%s" % (operation, ", ".join(step.node_names)))
        return tuple(lines)


@dataclass(frozen=True)
class ExecutionReceipt:
    plan_id: str
    success: bool
    applied_steps: int
    affected_nodes: Tuple[str, ...]
    executed_at: str
    message: str
    verified: bool = False
    rolled_back: bool = False


def plan_for_issue(issue: Issue, snapshot: SceneSnapshot) -> Optional[ChangePlan]:
    """Return a conservative plan; diagnostic issues deliberately return None."""
    if issue.suggested_action != "delete_unknown_nodes":
        return None
    node_map = snapshot.node_map
    candidates = tuple(
        node for node_id in issue.affected_node_ids
        if (node := node_map.get(node_id)) is not None and not node.referenced
    )
    if not candidates:
        return None
    step = ChangeStep(
        operation="delete_nodes",
        node_ids=tuple(node.id for node in candidates),
        node_names=tuple(node.dag_paths[0] if node.dag_paths else node.name for node in candidates),
        reason="移除本地未知节点残留；引用节点保持受保护。",
    )
    return ChangePlan(
        id="plan-%s" % uuid4().hex[:12],
        title="移除本地未知节点",
        issue_id=issue.id,
        steps=(step,),
        destructive=True,
        issue_ids=(issue.id,),
    )


def plan_for_issues(
    issues: Sequence[Issue], snapshot: SceneSnapshot
) -> Optional[ChangePlan]:
    """Compose repairable findings into one deduplicated atomic ChangePlan."""
    plans = tuple(
        plan for issue in issues
        if (plan := plan_for_issue(issue, snapshot)) is not None
    )
    if not plans:
        return None
    names_by_identity = {}
    operations_by_identity = {}
    reasons = []
    issue_ids = []
    for plan in plans:
        issue_ids.extend(plan.issue_ids)
        for step in plan.steps:
            reasons.append(step.reason)
            for node_id, name in zip(step.node_ids, step.node_names):
                existing_name = names_by_identity.setdefault(node_id, name)
                existing_operation = operations_by_identity.setdefault(node_id, step.operation)
                if existing_name != name or existing_operation != step.operation:
                    raise ValueError(
                        "Conflicting ChangePlan intent for stable node %s" % node_id
                    )
    grouped = {}
    for node_id, operation in operations_by_identity.items():
        grouped.setdefault(operation, []).append(node_id)
    steps = []
    for operation in sorted(grouped):
        node_ids = tuple(sorted(grouped[operation]))
        steps.append(
            ChangeStep(
                operation,
                node_ids,
                tuple(names_by_identity[node_id] for node_id in node_ids),
                "已复核发现的批量处理：%s" % " | ".join(dict.fromkeys(reasons)),
            )
        )
    unique_issue_ids = tuple(dict.fromkeys(issue_ids))
    return ChangePlan(
        id="batch-%s" % uuid4().hex[:12],
        title="场景诊所批量修复 · %s 项发现" % len(unique_issue_ids),
        issue_id=unique_issue_ids[0],
        issue_ids=unique_issue_ids,
        steps=tuple(steps),
        destructive=any(plan.destructive for plan in plans),
    )


class MayaChangeExecutor:
    """Executes only allow-listed operations inside one Maya undo chunk."""

    ALLOWED_OPERATIONS = frozenset({"delete_nodes"})

    def __init__(self, cmds_module: Any = None):
        if cmds_module is None:
            try:
                import maya.cmds as cmds_module  # type: ignore
            except ImportError as exc:
                raise RuntimeError("Maya 命令当前不可用") from exc
        self.cmds = cmds_module

    def preview(self, plan: ChangePlan) -> Tuple[str, ...]:
        return plan.preview_lines()

    def execute(self, plan: ChangePlan) -> ExecutionReceipt:
        if not plan.steps:
            raise ValueError("Refusing to execute an empty ChangePlan")
        invalid = [step.operation for step in plan.steps if step.operation not in self.ALLOWED_OPERATIONS]
        if invalid:
            raise ValueError("Unsupported ChangePlan operation: %s" % invalid[0])

        # Revalidate scene state at commit time; previews may become stale.
        resolved_steps = []
        try:
            for step in plan.steps:
                names = []
                for expected_id, name in zip(step.node_ids, step.node_names):
                    if not self.cmds.objExists(name):
                        continue
                    if not self._identity_matches(name, expected_id):
                        raise RuntimeError("ChangePlan is stale; node identity changed: %s" % name)
                    if self._is_referenced(name):
                        raise RuntimeError("Refusing to modify referenced node: %s" % name)
                    names.append(name)
                if names:
                    resolved_steps.append((step, tuple(names)))
        except Exception as exc:
            return self._receipt(plan, False, 0, (), str(exc))
        if not resolved_steps:
            return self._receipt(plan, True, 0, (), "场景已经满足该变更计划")

        applied_steps = 0
        affected = []
        chunk_open = False
        mutated = False
        try:
            self.cmds.undoInfo(openChunk=True, chunkName="MayaScope: %s" % plan.title)
            chunk_open = True
            for step, names in resolved_steps:
                # Mark intent before the host call: a Maya command can mutate
                # partially and still raise, in which case the chunk must undo.
                mutated = True
                if step.operation == "delete_nodes":
                    self.cmds.delete(list(names))
                    remaining = tuple(name for name in names if self.cmds.objExists(name))
                    if remaining:
                        raise RuntimeError(
                            "变更计划后置条件失败；以下节点仍然存在：%s"
                            % ", ".join(remaining)
                        )
                applied_steps += 1
                affected.extend(names)
        except Exception as exc:
            if chunk_open:
                self.cmds.undoInfo(closeChunk=True)
                chunk_open = False
            if mutated:
                try:
                    self.cmds.undo()
                except Exception:
                    pass
            return self._receipt(
                plan, False, applied_steps, tuple(affected), str(exc), rolled_back=mutated
            )
        finally:
            if chunk_open:
                self.cmds.undoInfo(closeChunk=True)

        return self._receipt(
            plan,
            True,
            applied_steps,
            tuple(affected),
            "变更已应用并通过宿主后置条件验证；需要重新捕获场景",
            verified=True,
        )

    def _is_referenced(self, name: str) -> bool:
        try:
            return bool(self.cmds.referenceQuery(name, isNodeReferenced=True))
        except RuntimeError:
            return False

    def _identity_matches(self, name: str, expected_id: str) -> bool:
        # Test doubles and older command wrappers may not expose UUID queries.
        if not hasattr(self.cmds, "ls"):
            return True
        identities = self.cmds.ls(name, uuid=True) or []
        return not identities or expected_id in identities

    @staticmethod
    def _receipt(
        plan: ChangePlan,
        success: bool,
        applied_steps: int,
        affected: Tuple[str, ...],
        message: str,
        verified: bool = False,
        rolled_back: bool = False,
    ) -> ExecutionReceipt:
        return ExecutionReceipt(
            plan_id=plan.id,
            success=success,
            applied_steps=applied_steps,
            affected_nodes=affected,
            executed_at=datetime.now(timezone.utc).isoformat(),
            message=message,
            verified=verified,
            rolled_back=rolled_back,
        )
