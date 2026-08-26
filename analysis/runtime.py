"""Evidence-first analysis of volatile Maya execution surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Tuple

from ..model import RuntimeSnapshot, SceneSnapshot
from .rules import Evidence, Issue, Severity


def _runtime_issue_id(rule_id, identities):
    basis = "%s|%s" % (rule_id, "|".join(sorted(str(item) for item in identities)))
    return "%s:%s" % (rule_id, hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10])


@dataclass(frozen=True)
class RuntimeReport:
    runtime_id: str
    issues: Tuple[Issue, ...]
    limitations: Tuple[str, ...]

    @property
    def affected_node_ids(self):
        return tuple(sorted({node_id for issue in self.issues for node_id in issue.affected_node_ids}))


def analyze_runtime(runtime: RuntimeSnapshot, scene: SceneSnapshot, callback_threshold=8):
    if runtime.source_snapshot_id != scene.snapshot_id:
        raise ValueError("RuntimeSnapshot does not belong to the supplied SceneSnapshot")
    if callback_threshold < 1:
        raise ValueError("callback_threshold must be positive")
    known = set(scene.node_map)
    issues = []
    limitations = [runtime.callback_visibility]
    if not runtime.script_jobs_available:
        limitations.append("Maya batch / standalone 模式下无法获取 scriptJob 清单")
    if runtime.metadata.get("script_job_parse_failures"):
        limitations.append("一个或多个 scriptJob 描述无法解析")

    if runtime.expressions:
        affected = tuple(item.node_id for item in runtime.expressions if item.node_id in known)
        always = tuple(item for item in runtime.expressions if item.always_evaluate)
        issues.append(
            Issue(
                id=_runtime_issue_id("runtime-expressions", affected or (item.node_name for item in runtime.expressions)),
                rule_id="runtime-expressions",
                title="表达式执行表面",
                description="表达式会在求值期间执行，可能在显式 DG 连线之外隐藏依赖或串行工作。",
                severity=Severity.WARNING if always else Severity.INFO,
                affected_node_ids=affected,
                evidence=(
                    Evidence("表达式", str(len(runtime.expressions))),
                    Evidence("始终求值", str(len(always))),
                    Evidence("示例", ", ".join(item.node_name for item in runtime.expressions[:6])),
                    Evidence("源码身份", ", ".join(item.source_sha256[:10] for item in runtime.expressions[:6])),
                ),
            )
        )

    if runtime.script_jobs_available and runtime.script_jobs:
        risky = tuple(
            item for item in runtime.script_jobs
            if item.trigger_kind == "idle" or item.permanent or item.protected
        )
        issues.append(
            Issue(
                id=_runtime_issue_id("runtime-script-jobs", (item.descriptor_sha256 for item in runtime.script_jobs)),
                rule_id="runtime-script-jobs",
                title="交互式 scriptJob 表面",
                description="scriptJob 会在场景 DG 之外响应 Maya 事件，可能常驻、形成事件风暴，或在艺术家交互期间修改状态。",
                severity=Severity.WARNING if risky else Severity.INFO,
                affected_node_ids=(),
                evidence=(
                    Evidence("任务数", str(len(runtime.script_jobs))),
                    Evidence("受保护 / 常驻 / 空闲触发", str(len(risky))),
                    Evidence("触发器", ", ".join("%s:%s" % (item.trigger_kind, item.trigger) for item in runtime.script_jobs[:8])),
                    Evidence("安全边界", "仅清点；绝不会自动终止任务"),
                ),
            )
        )

    if runtime.node_callbacks:
        hotspots = tuple(item for item in runtime.node_callbacks if item.callback_count >= callback_threshold)
        affected = tuple(item.node_id for item in hotspots if item.node_id in known)
        total = sum(item.callback_count for item in runtime.node_callbacks)
        issues.append(
            Issue(
                id=_runtime_issue_id("runtime-node-callbacks", (item.node_id for item in runtime.node_callbacks)),
                rule_id="runtime-node-callbacks",
                title="不透明节点回调足迹",
                description="Maya 仅暴露节点范围的回调 ID，不提供全局所有者或函数注册表；回调存在本身是证据，但不能据此归因。",
                severity=Severity.WARNING if hotspots else Severity.INFO,
                affected_node_ids=affected,
                evidence=(
                    Evidence("含回调的节点", str(len(runtime.node_callbacks))),
                    Evidence("不透明回调 ID", str(total)),
                    Evidence("热点 ≥ %s" % callback_threshold, str(len(hotspots))),
                    Evidence("归因边界", runtime.callback_visibility),
                ),
            )
        )

    third_party = tuple(
        item for item in runtime.plugins
        if item.vendor and "autodesk" not in item.vendor.lower()
    )
    if third_party:
        issues.append(
            Issue(
                id=_runtime_issue_id("runtime-third-party-plugins", (item.name for item in third_party)),
                rule_id="runtime-third-party-plugins",
                title="第三方插件执行表面",
                description="已加载的非 Autodesk 插件会引入原生或 Python 代码、注册节点、命令与序列化依赖。",
                severity=Severity.INFO,
                affected_node_ids=(),
                evidence=(
                    Evidence("第三方插件", str(len(third_party))),
                    Evidence("示例", ", ".join("%s %s" % (item.name, item.version) for item in third_party[:8])),
                    Evidence("安全边界", "仅清点；绝不会自动卸载插件"),
                ),
            )
        )

    issues.sort(key=lambda item: (-int(item.severity), item.rule_id, item.id))
    return RuntimeReport(runtime.runtime_id, tuple(issues), tuple(limitations))
