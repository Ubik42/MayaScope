"""Evidence-first scene health rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import hashlib
from typing import Iterable, Mapping, Protocol, Sequence, Tuple

from .graph import get_graph_index
from ..model import SceneNode, SceneSnapshot


class Severity(IntEnum):
    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40


@dataclass(frozen=True)
class Evidence:
    label: str
    value: str


@dataclass(frozen=True)
class Issue:
    id: str
    rule_id: str
    title: str
    description: str
    severity: Severity
    affected_node_ids: Tuple[str, ...]
    evidence: Tuple[Evidence, ...]
    suggested_action: str = ""
    atomic_subjects: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "affected_node_ids", tuple(self.affected_node_ids))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(
            self,
            "atomic_subjects",
            tuple((str(subject), str(node_id)) for subject, node_id in self.atomic_subjects),
        )
        subject_ids = [subject for subject, _node_id in self.atomic_subjects]
        if any(not subject for subject in subject_ids):
            raise ValueError("Issue atomic subject ids cannot be empty")
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("Issue atomic subject ids must be unique")


class Rule(Protocol):
    id: str

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]: ...


def _issue_id(rule_id: str, node_ids: Iterable[str]) -> str:
    basis = "%s|%s" % (rule_id, "|".join(sorted(node_ids)))
    return "%s:%s" % (rule_id, hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10])


class UnknownNodeRule:
    id = "unknown-nodes"
    UNKNOWN_TYPES = frozenset({"unknown", "unknownDag", "unknownTransform"})

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        nodes = tuple(node for node in snapshot.nodes if node.type_name in self.UNKNOWN_TYPES)
        if not nodes:
            return ()
        local = tuple(node for node in nodes if not node.referenced)
        referenced = tuple(node for node in nodes if node.referenced)
        origins = sorted(
            {
                str(node.metadata.get("unknown_plugin", ""))
                for node in nodes
                if node.metadata.get("unknown_plugin")
            }
        )
        real_types = sorted(
            {
                str(node.metadata.get("unknown_real_class", ""))
                for node in nodes
                if node.metadata.get("unknown_real_class")
            }
        )
        evidence = (
            Evidence("未知节点", str(len(nodes))),
            Evidence("本地 / 可移除", str(len(local))),
            Evidence("引用 / 受保护", str(len(referenced))),
            Evidence("来源插件", ", ".join(origins[:6]) if origins else "场景未保留来源"),
            Evidence("原始类型", ", ".join(real_types[:8]) if real_types else "场景未保留类型"),
            Evidence("示例", ", ".join(node.name for node in nodes[:6])),
        )
        return (
            Issue(
                id=_issue_id(self.id, (node.id for node in nodes)),
                rule_id=self.id,
                title="未知节点残留",
                description=(
                    "定义这些节点的插件当前不可用，可能导致发布、序列化或下游场景加载失败。"
                ),
                severity=Severity.ERROR,
                affected_node_ids=tuple(node.id for node in nodes),
                evidence=evidence,
                suggested_action="delete_unknown_nodes" if local else "",
                atomic_subjects=tuple(("unknown-node:%s" % node.id, node.id) for node in nodes),
            ),
        )


class MissingPluginRequirementRule:
    id = "missing-plugin-requirements"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        plugins = tuple(snapshot.unknown_plugins)
        if not plugins:
            return ()
        names = {plugin.name for plugin in plugins}
        nodes = tuple(
            node
            for node in snapshot.nodes
            if str(node.metadata.get("unknown_plugin", "")) in names
        )
        node_types = sorted({value for plugin in plugins for value in plugin.node_types})
        data_types = sorted({value for plugin in plugins for value in plugin.data_types})
        versions = ", ".join(
            "%s %s" % (plugin.name, plugin.version or "版本未知") for plugin in plugins[:6]
        )
        return (
            Issue(
                id=_issue_id(self.id, ("plugin:%s" % plugin.name for plugin in plugins)),
                rule_id=self.id,
                title="场景依赖的插件缺失",
                description=(
                    "Maya 已从场景 requires 记录确认这些插件不可用；其节点或数据可能降级为未知类型，"
                    "求值、保存和下游发布结果不再可信。"
                ),
                severity=Severity.ERROR,
                affected_node_ids=tuple(node.id for node in nodes),
                evidence=(
                    Evidence("缺失插件", str(len(plugins))),
                    Evidence("插件 / 版本", versions),
                    Evidence("注册节点类型", ", ".join(node_types[:10]) if node_types else "未记录"),
                    Evidence("注册数据类型", ", ".join(data_types[:10]) if data_types else "未记录"),
                    Evidence("已关联未知节点", str(len(nodes))),
                    Evidence("安全边界", "仅诊断；不会自动加载、删除或替换插件"),
                ),
                atomic_subjects=tuple(
                    ("unknown-plugin:%s" % plugin.name, "") for plugin in plugins
                ),
            ),
        )


class CycleRule:
    id = "dg-cycles"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        result = []
        names = snapshot.node_map
        for component in get_graph_index(snapshot).strongly_connected_components():
            result.append(
                Issue(
                    id=_issue_id(self.id, component),
                    rule_id=self.id,
                    title="DG 依赖循环",
                    description="强连通 DG 分量会放大脏数据传播，并使求值过程更难定位。",
                    severity=Severity.CRITICAL if len(component) > 8 else Severity.ERROR,
                    affected_node_ids=component,
                    evidence=(
                        Evidence("分量规模", str(len(component))),
                        Evidence("节点", ", ".join(names[node].name for node in component[:8])),
                    ),
                )
            )
        return result


class HighFanoutRule:
    id = "high-fanout"

    def __init__(self, threshold: int = 64):
        self.threshold = threshold

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        graph = get_graph_index(snapshot)
        result = []
        for node_id, targets in graph.forward.items():
            if len(targets) < self.threshold:
                continue
            node = snapshot.node_map[node_id]
            result.append(
                Issue(
                    id=_issue_id(self.id, (node_id,)),
                    rule_id=self.id,
                    title="高扇出热点",
                    description="单个节点会直接触发异常广泛的依赖图脏化。",
                    severity=Severity.WARNING,
                    affected_node_ids=(node_id,),
                    evidence=(Evidence("节点", node.name), Evidence("直接依赖数", str(len(targets)))),
                )
            )
        return result


class CrossReferenceConnectionRule:
    id = "cross-reference-links"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        nodes = snapshot.node_map
        pairs = set()
        affected = set()
        for edge in snapshot.edges:
            if edge.relation != "dg":
                continue
            source, target = nodes[edge.source_id], nodes[edge.target_id]
            if not source.referenced or not target.referenced:
                continue
            if source.reference_file and target.reference_file and source.reference_file != target.reference_file:
                pairs.add((source.reference_file, target.reference_file))
                affected.update((source.id, target.id))
        if not pairs:
            return ()
        return (
            Issue(
                id=_issue_id(self.id, affected),
                rule_id=self.id,
                title="跨引用依赖",
                description="连接跨越了不同引用文件，可能形成脆弱的加载顺序耦合。",
                severity=Severity.WARNING,
                affected_node_ids=tuple(sorted(affected)),
                evidence=(
                    Evidence("引用文件对", str(len(pairs))),
                    Evidence("连接", "; ".join("%s → %s" % pair for pair in sorted(pairs)[:4])),
                ),
            ),
        )


class OrphanUtilityRule:
    id = "orphan-utilities"
    UTILITY_TYPES = frozenset(
        {
            "multiplyDivide", "plusMinusAverage", "condition", "blendColors",
            "remapValue", "unitConversion", "reverse", "clamp", "setRange",
            "vectorProduct", "composeMatrix", "multMatrix", "decomposeMatrix",
            "wtAddMatrix", "choice",
        }
    )

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        connected = {
            node_id
            for edge in snapshot.edges
            if edge.relation == "dg"
            for node_id in (edge.source_id, edge.target_id)
        }
        nodes = tuple(
            node
            for node in snapshot.nodes
            if node.type_name in self.UTILITY_TYPES
            and node.id not in connected
            and not node.referenced
        )
        if not nodes:
            return ()
        return (
            Issue(
                id=_issue_id(self.id, (node.id for node in nodes)),
                rule_id=self.id,
                title="游离工具节点残留",
                description=(
                    "这些本地工具节点没有捕获到 DG 输入或输出，可能是废弃的绑定或动画图残留；纯脚本用途无法观测，删除前必须人工复核。"
                ),
                severity=Severity.INFO,
                affected_node_ids=tuple(node.id for node in nodes),
                evidence=(
                    Evidence("游离工具节点", str(len(nodes))),
                    Evidence("示例", ", ".join(node.name for node in nodes[:8])),
                    Evidence("安全边界", "仅诊断；无法推断纯脚本所有权"),
                ),
            ),
        )


class NamespaceDepthRule:
    id = "namespace-depth"

    def __init__(self, threshold: int = 3):
        if threshold < 1:
            raise ValueError("threshold must be positive")
        self.threshold = threshold

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        nodes = tuple(
            node for node in snapshot.nodes
            if node.namespace and node.namespace.count(":") + 1 > self.threshold
        )
        if not nodes:
            return ()
        deepest = max(node.namespace.count(":") + 1 for node in nodes)
        return (
            Issue(
                id=_issue_id(self.id, (node.id for node in nodes)),
                rule_id=self.id,
                title="命名空间嵌套过深",
                description="过深的命名空间会让发布路径、引用编辑和依赖名称的流程集成更加脆弱。",
                severity=Severity.WARNING,
                affected_node_ids=tuple(node.id for node in nodes),
                evidence=(
                    Evidence("超过深度 %s 的节点" % self.threshold, str(len(nodes))),
                    Evidence("最大深度", str(deepest)),
                    Evidence("示例", ", ".join(node.name for node in nodes[:6])),
                ),
            ),
        )


class NodeTypePolicyRule:
    """Declarative studio policy; deliberately offers no executable callback."""

    def __init__(
        self,
        rule_id: str,
        title: str,
        node_types: Iterable[str],
        description: str,
        severity: Severity = Severity.WARNING,
    ):
        self.id = rule_id
        self.title = title
        self.node_types = frozenset(str(value) for value in node_types)
        self.description = description
        self.severity = severity
        if not self.id or not self.title or not self.node_types:
            raise ValueError("NodeTypePolicyRule requires id, title, and node types")

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        nodes = tuple(node for node in snapshot.nodes if node.type_name in self.node_types)
        if not nodes:
            return ()
        return (
            Issue(
                id=_issue_id(self.id, (node.id for node in nodes)),
                rule_id=self.id,
                title=self.title,
                description=self.description,
                severity=self.severity,
                affected_node_ids=tuple(node.id for node in nodes),
                evidence=(
                    Evidence("策略节点类型", ", ".join(sorted(self.node_types))),
                    Evidence("命中数量", str(len(nodes))),
                    Evidence("示例", ", ".join(node.name for node in nodes[:8])),
                ),
            ),
        )


@dataclass(frozen=True)
class SceneContract:
    """Declarative studio scene policy; empty fields impose no opinion."""

    allowed_time_units: Tuple[str, ...] = ()
    required_linear_unit: str = ""
    required_angular_unit: str = ""
    required_up_axis: str = ""
    required_color_management: bool | None = None
    allowed_rendering_spaces: Tuple[str, ...] = ()
    required_plugins: Tuple[str, ...] = ()
    forbidden_plugins: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_time_units", tuple(self.allowed_time_units))
        object.__setattr__(self, "allowed_rendering_spaces", tuple(self.allowed_rendering_spaces))
        object.__setattr__(self, "required_plugins", tuple(self.required_plugins))
        object.__setattr__(self, "forbidden_plugins", tuple(self.forbidden_plugins))


class SceneContractRule:
    id = "scene-contract"

    def __init__(self, contract: SceneContract, severity: Severity = Severity.ERROR):
        self.contract = contract
        self.severity = severity

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        settings = snapshot.scene_settings
        contract = self.contract
        mismatches = []

        def mismatch(key: str, label: str, expected: str, actual: str) -> None:
            mismatches.append((key, Evidence(label, "要求 %s · 当前 %s" % (expected, actual or "不可读取"))))

        if contract.allowed_time_units and settings.time_unit not in contract.allowed_time_units:
            mismatch("time", "时间单位 / 帧率", " / ".join(contract.allowed_time_units), settings.time_unit)
        if contract.required_linear_unit and settings.linear_unit != contract.required_linear_unit:
            mismatch("linear", "线性单位", contract.required_linear_unit, settings.linear_unit)
        if contract.required_angular_unit and settings.angular_unit != contract.required_angular_unit:
            mismatch("angular", "角度单位", contract.required_angular_unit, settings.angular_unit)
        if contract.required_up_axis and settings.up_axis != contract.required_up_axis:
            mismatch("axis", "场景上轴", contract.required_up_axis.upper(), settings.up_axis.upper())
        if contract.required_color_management is not None:
            actual = settings.color_management_enabled
            if actual is not contract.required_color_management:
                mismatch(
                    "color-enabled",
                    "色彩管理",
                    "启用" if contract.required_color_management else "停用",
                    "启用" if actual is True else "停用" if actual is False else "不可读取",
                )
        if (
            contract.allowed_rendering_spaces
            and settings.rendering_space not in contract.allowed_rendering_spaces
        ):
            mismatch(
                "render-space",
                "渲染空间",
                " / ".join(contract.allowed_rendering_spaces),
                settings.rendering_space,
            )
        plugins = frozenset(str(value) for value in snapshot.metadata.get("plugins_in_use", ()))
        missing_plugins = tuple(sorted(set(contract.required_plugins).difference(plugins)))
        if missing_plugins:
            mismatch("required-plugins", "缺失必要插件", ", ".join(missing_plugins), "未加载")
        forbidden_plugins = tuple(sorted(set(contract.forbidden_plugins).intersection(plugins)))
        if forbidden_plugins:
            mismatch("forbidden-plugins", "禁用插件命中", "不允许使用", ", ".join(forbidden_plugins))
        if not mismatches:
            return ()
        return (
            Issue(
                id=_issue_id(self.id, (item[0] for item in mismatches)),
                rule_id=self.id,
                title="场景制片规范不一致",
                description="场景级设置偏离项目契约，可能造成动画时序漂移、尺度错误或发布环境不一致。",
                severity=self.severity,
                affected_node_ids=(),
                evidence=tuple(item[1] for item in mismatches),
                atomic_subjects=tuple(
                    ("scene-contract:%s" % item[0], "") for item in mismatches
                ),
            ),
        )


class UnloadedReferenceRule:
    id = "unloaded-references"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        references = tuple(reference for reference in snapshot.references if not reference.loaded)
        if not references:
            return ()
        affected = tuple(sorted({node_id for reference in references for node_id in reference.node_ids}))
        return (
            Issue(
                id=_issue_id(self.id, (reference.reference_node for reference in references)),
                rule_id=self.id,
                title="未加载引用范围",
                description="未加载的引用会隐藏节点级拓扑，导致当前快照的验证范围不完整。",
                severity=Severity.WARNING,
                affected_node_ids=affected,
                evidence=(
                    Evidence("未加载引用", str(len(references))),
                    Evidence("引用节点", ", ".join(reference.reference_node for reference in references[:8])),
                    Evidence("文件", ", ".join(reference.unresolved_path or reference.resolved_path for reference in references[:5])),
                    Evidence("可见性", "引用未加载时无法获取其节点成员关系"),
                ),
            ),
        )


class MissingReferenceFileRule:
    id = "missing-reference-files"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        references = tuple(
            reference for reference in snapshot.references if reference.exists is False
        )
        if not references:
            return ()
        affected = tuple(
            sorted({node_id for reference in references for node_id in reference.node_ids})
        )
        by_path = {}
        for reference in references:
            canonical = reference.canonical_path or reference.resolved_path
            key = canonical.replace("\\", "/").casefold()
            by_path.setdefault(key, canonical)
        subjects = tuple(
            (
                "missing-reference-file:%s"
                % hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],
                "",
            )
            for key in sorted(by_path)
        )
        return (
            Issue(
                id=_issue_id(self.id, (reference.reference_node for reference in references)),
                rule_id=self.id,
                title="引用源文件缺失",
                description=(
                    "Maya 保留了 reference node，但规范化源文件不可达；引用成员不会加载，"
                    "当前拓扑和发布检查范围因此不完整。"
                ),
                severity=Severity.ERROR,
                affected_node_ids=affected,
                evidence=(
                    Evidence("缺失引用实例", str(len(references))),
                    Evidence("缺失源文件", str(len(by_path))),
                    Evidence(
                        "引用节点",
                        ", ".join(reference.reference_node for reference in references[:8]),
                    ),
                    Evidence(
                        "命名空间",
                        ", ".join(reference.namespace or "不可读取" for reference in references[:8]),
                    ),
                    Evidence("路径样例", " | ".join(by_path[key] for key in sorted(by_path)[:5])),
                    Evidence("检查边界", "UNC 网络路径不在主线程主动探测，状态会保留为未知"),
                ),
                atomic_subjects=subjects,
            ),
        )


class ReferenceNamespaceIntrusionRule:
    id = "reference-namespace-intrusion"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        namespaces = {
            reference.namespace.strip(":")
            for reference in snapshot.references
            if reference.namespace.strip(":")
        }
        if not namespaces:
            return ()
        intruders = []
        owners = {}
        for node in snapshot.nodes:
            if node.referenced or not node.namespace:
                continue
            parts = node.namespace.split(":")
            owner = next(
                (
                    ":".join(parts[:depth])
                    for depth in range(len(parts), 0, -1)
                    if ":".join(parts[:depth]) in namespaces
                ),
                "",
            )
            if owner:
                intruders.append(node)
                owners.setdefault(owner, 0)
                owners[owner] += 1
        if not intruders:
            return ()
        return (
            Issue(
                id=_issue_id(self.id, (node.id for node in intruders)),
                rule_id=self.id,
                title="本地节点侵入引用命名空间",
                description=(
                    "本地节点使用了由文件引用占用的 namespace；引用重载、移除、导出或发布时"
                    "对象归属容易混淆，并可能把本地残留误当成资产内容。"
                ),
                severity=Severity.ERROR,
                affected_node_ids=tuple(node.id for node in intruders),
                evidence=(
                    Evidence("越界本地节点", str(len(intruders))),
                    Evidence("受影响引用命名空间", str(len(owners))),
                    Evidence(
                        "归属分布",
                        " · ".join("%s %s" % item for item in sorted(owners.items())),
                    ),
                    Evidence("节点样例", ", ".join(node.name for node in intruders[:8])),
                    Evidence("安全边界", "仅诊断；不会自动移动 namespace 或重命名节点"),
                ),
                atomic_subjects=tuple(
                    ("reference-namespace-intrusion:%s" % node.id, node.id)
                    for node in intruders
                ),
            ),
        )


class FailedReferenceEditRule:
    id = "failed-reference-edits"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        references = tuple(
            reference for reference in snapshot.references if reference.failed_edit_count
        )
        if not references:
            return ()
        affected = tuple(sorted({node_id for reference in references for node_id in reference.node_ids}))
        samples = tuple(
            sample
            for reference in references
            for sample in reference.failed_edit_samples
        )
        return (
            Issue(
                id=_issue_id(self.id, (reference.reference_node for reference in references)),
                rule_id=self.id,
                title="引用编辑应用失败",
                description="Maya 无法将已存储的编辑应用到当前引用内容；预期覆盖可能缺失或已经过期。",
                severity=Severity.ERROR,
                affected_node_ids=affected,
                evidence=(
                    Evidence("失败编辑数", str(sum(reference.failed_edit_count for reference in references))),
                    Evidence("引用", ", ".join(reference.reference_node for reference in references[:8])),
                    Evidence("样例", " | ".join(samples[:4]) if samples else "未保留编辑字符串"),
                ),
            ),
        )


class NestedReferenceDepthRule:
    id = "nested-reference-depth"

    def __init__(self, threshold: int = 2):
        if threshold < 1:
            raise ValueError("threshold must be positive")
        self.threshold = threshold

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        by_name = {reference.reference_node: reference for reference in snapshot.references}
        deep = []
        max_depth = 0
        for reference in snapshot.references:
            depth = 1
            current = reference
            seen = {reference.reference_node}
            while current.parent_reference_node in by_name:
                parent = current.parent_reference_node
                if parent in seen:
                    break
                seen.add(parent)
                depth += 1
                current = by_name[parent]
            if depth > self.threshold:
                deep.append(reference)
                max_depth = max(max_depth, depth)
        if not deep:
            return ()
        affected = tuple(sorted({node_id for reference in deep for node_id in reference.node_ids}))
        return (
            Issue(
                id=_issue_id(self.id, (reference.reference_node for reference in deep)),
                rule_id=self.id,
                title="引用嵌套链过深",
                description="深层引用组合会增加加载顺序、编辑归属与发布排障的复杂度。",
                severity=Severity.WARNING,
                affected_node_ids=affected,
                evidence=(
                    Evidence("超过深度 %s 的引用" % self.threshold, str(len(deep))),
                    Evidence("最大深度", str(max_depth)),
                    Evidence("引用节点", ", ".join(reference.reference_node for reference in deep[:8])),
                ),
            ),
        )


class UnsavedSceneRule:
    id = "unsaved-scene"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        if snapshot.source_scene:
            return ()
        return (
            Issue(
                id=_issue_id(self.id, ("scene",)),
                rule_id=self.id,
                title="场景尚未保存",
                description="未命名场景无法提供稳定的发布路径、归档来源或可靠的相对文件上下文。",
                severity=Severity.WARNING,
                affected_node_ids=(),
                evidence=(Evidence("场景路径", "未命名"), Evidence("范围", "场景级")),
            ),
        )


class UnsavedSceneChangesRule:
    id = "unsaved-scene-changes"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        if snapshot.scene_lifecycle.modified is not True:
            return ()
        lifecycle = snapshot.scene_lifecycle
        return (
            Issue(
                id=_issue_id(self.id, ("scene",)),
                rule_id=self.id,
                title="场景存在未保存修改",
                description="当前 Maya 内存状态与磁盘文件不同；归档、批处理和发布门禁无法复现这些改动。",
                severity=Severity.WARNING,
                affected_node_ids=(),
                evidence=(
                    Evidence("内存修改状态", "已修改 / 尚未保存"),
                    Evidence("文件类型", lifecycle.file_type or "未命名"),
                    Evidence(
                        "播放范围",
                        "%g–%g（动画 %g–%g）"
                        % (
                            lifecycle.playback_min,
                            lifecycle.playback_max,
                            lifecycle.animation_start,
                            lifecycle.animation_end,
                        ),
                    ),
                    Evidence("当前时间", "%g" % lifecycle.current_time),
                ),
            ),
        )


class RuntimeScriptNodeRule:
    id = "runtime-script-nodes"
    TYPES = frozenset({"script"})
    MAYA_CONFIGURATION_NODES = frozenset(
        {"uiConfigurationScriptNode", "sceneConfigurationScriptNode"}
    )

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        nodes = tuple(
            node for node in snapshot.nodes
            if node.type_name in self.TYPES
            and node.name.rsplit(":", 1)[-1] not in self.MAYA_CONFIGURATION_NODES
        )
        if not nodes:
            return ()
        return (
            Issue(
                id=_issue_id(self.id, (node.id for node in nodes)),
                rule_id=self.id,
                title="存在运行时脚本节点",
                description="脚本节点可在场景生命周期事件中执行代码；发布前必须区分合法流程用途与意外载荷。",
                severity=Severity.WARNING,
                affected_node_ids=tuple(node.id for node in nodes),
                evidence=(
                    Evidence("脚本节点", str(len(nodes))),
                    Evidence("示例", ", ".join(node.name for node in nodes[:8])),
                    Evidence("安全边界", "仅诊断；不会推断代码意图"),
                ),
            ),
        )


class OrphanAnimationCurveRule:
    id = "orphan-animation-curves"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        connected = {
            node_id
            for edge in snapshot.edges
            if edge.relation == "dg"
            for node_id in (edge.source_id, edge.target_id)
        }
        nodes = tuple(
            node for node in snapshot.nodes
            if node.type_name.startswith("animCurve")
            and node.id not in connected
            and not node.referenced
        )
        if not nodes:
            return ()
        return (
            Issue(
                id=_issue_id(self.id, (node.id for node in nodes)),
                rule_id=self.id,
                title="游离动画曲线",
                description="这些本地动画曲线没有捕获到 DG 连接，可能是废弃关键帧，但无法排除非 DG 脚本所有权。",
                severity=Severity.INFO,
                affected_node_ids=tuple(node.id for node in nodes),
                evidence=(
                    Evidence("游离曲线", str(len(nodes))),
                    Evidence("示例", ", ".join(node.name for node in nodes[:8])),
                    Evidence("安全边界", "仅诊断；需要人工复核所有权"),
                ),
            ),
        )


class MissingExternalDependencyRule:
    id = "missing-external-files"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        missing = tuple(
            dependency
            for dependency in snapshot.external_dependencies
            if dependency.exists is False
        )
        if not missing:
            return ()
        affected = tuple(sorted({dependency.node_id for dependency in missing}))
        by_kind = {}
        for dependency in missing:
            by_kind[dependency.kind] = by_kind.get(dependency.kind, 0) + 1
        return (
            Issue(
                id=_issue_id(self.id, affected),
                rule_id=self.id,
                title="外部文件依赖缺失",
                description="Maya 路径注册表无法解析这些文件，打开、播放、渲染或发布时可能出现空内容。",
                severity=Severity.ERROR,
                affected_node_ids=affected,
                evidence=(
                    Evidence("缺失依赖", str(len(missing))),
                    Evidence(
                        "类型",
                        " · ".join("%s %s" % item for item in sorted(by_kind.items())),
                    ),
                    Evidence("路径样例", " | ".join(item.raw_path for item in missing[:5])),
                    Evidence("检查来源", "Maya filePathEditor 状态；未递归扫描磁盘"),
                ),
                atomic_subjects=tuple((item.id, item.node_id) for item in missing),
            ),
        )


class NonPortableExternalDependencyRule:
    id = "nonportable-external-files"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        dependencies = tuple(
            dependency
            for dependency in snapshot.external_dependencies
            if dependency.exists is not False
            and (
                dependency.path_kind == "network"
                or (
                    dependency.path_kind == "absolute"
                    and dependency.inside_workspace is False
                )
            )
        )
        if not dependencies:
            return ()
        affected = tuple(sorted({dependency.node_id for dependency in dependencies}))
        network = sum(item.path_kind == "network" for item in dependencies)
        outside = sum(item.path_kind == "absolute" for item in dependencies)
        return (
            Issue(
                id=_issue_id(self.id, affected),
                rule_id=self.id,
                title="外部依赖不可移植",
                description="场景依赖了工作区之外的绝对路径或网络路径，换机器、打包或农场执行时存在漂移风险。",
                severity=Severity.WARNING,
                affected_node_ids=affected,
                evidence=(
                    Evidence("风险依赖", str(len(dependencies))),
                    Evidence("工作区外绝对路径", str(outside)),
                    Evidence("网络路径", str(network)),
                    Evidence("路径样例", " | ".join(item.raw_path for item in dependencies[:5])),
                ),
                atomic_subjects=tuple(
                    (item.id, item.node_id) for item in dependencies
                ),
            ),
        )


class ExternalSequenceGapRule:
    id = "external-sequence-gaps"

    def evaluate(self, snapshot: SceneSnapshot) -> Sequence[Issue]:
        incomplete = tuple(
            dependency
            for dependency in snapshot.external_dependencies
            if dependency.sequence_kind == "frame"
            and dependency.sequence_scan_complete
            and bool(dependency.sequence_missing_count)
            and dependency.exists is not False
        )
        if not incomplete:
            return ()
        affected = tuple(sorted({dependency.node_id for dependency in incomplete}))
        missing_total = sum(int(item.sequence_missing_count or 0) for item in incomplete)
        expected_total = sum(int(item.sequence_expected_count or 0) for item in incomplete)
        samples = []
        for dependency in incomplete:
            if dependency.sequence_missing_samples:
                samples.append(
                    "%s：%s"
                    % (dependency.node_name, ", ".join(dependency.sequence_missing_samples[:6]))
                )
        return (
            Issue(
                id=_issue_id(self.id, affected),
                rule_id=self.id,
                title="缓存或序列帧存在缺口",
                description="本地序列在已经观测到的首尾编号之间并不连续，播放、模拟、渲染或发布可能在内部缺口退化为空内容。",
                severity=Severity.WARNING,
                affected_node_ids=affected,
                evidence=(
                    Evidence("不完整序列", str(len(incomplete))),
                    Evidence("已观测跨度应有", str(expected_total)),
                    Evidence("缺失成员", str(missing_total)),
                    Evidence("缺帧样例", " | ".join(samples[:5]) or "未保留样例"),
                    Evidence("安全边界", "只判断已观测编号跨度的内部空洞；不推断首尾帧，网络路径与超预算目录保持未知"),
                ),
                atomic_subjects=tuple((item.id, item.node_id) for item in incomplete),
            ),
        )
DEFAULT_RULES = (
    MissingPluginRequirementRule(),
    UnknownNodeRule(),
    CycleRule(),
    HighFanoutRule(),
    CrossReferenceConnectionRule(),
    OrphanUtilityRule(),
    NamespaceDepthRule(),
    MissingReferenceFileRule(),
    ReferenceNamespaceIntrusionRule(),
    UnloadedReferenceRule(),
    FailedReferenceEditRule(),
    NestedReferenceDepthRule(),
    UnsavedSceneRule(),
    UnsavedSceneChangesRule(),
    RuntimeScriptNodeRule(),
    OrphanAnimationCurveRule(),
    MissingExternalDependencyRule(),
    NonPortableExternalDependencyRule(),
    ExternalSequenceGapRule(),
)


def analyze_snapshot(snapshot: SceneSnapshot, rules: Sequence[Rule] = DEFAULT_RULES) -> Tuple[Issue, ...]:
    issues = [issue for rule in rules for issue in rule.evaluate(snapshot)]
    return tuple(sorted(issues, key=lambda issue: (-int(issue.severity), issue.title, issue.id)))
