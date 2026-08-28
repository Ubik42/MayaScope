"""Defensive Maya API 2.0 scene collector.

The collector owns all Maya-specific introspection. Analysis and UI consume only
SceneSnapshot, which keeps tests fast and future batch/remote probes possible.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ..model import (
    ExternalDependency,
    SceneEdge,
    SceneNode,
    SceneReference,
    SceneLifecycle,
    SceneSettings,
    SceneSnapshot,
    UnknownPlugin,
)
from .dependency_sequences import inspect_local_sequence


class MayaUnavailableError(RuntimeError):
    pass


class CaptureCancelled(RuntimeError):
    pass


class SceneChangedDuringCapture(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureProgress:
    stage: str
    completed: int
    total: int
    message: str

    @property
    def fraction(self) -> float:
        return self.completed / float(self.total) if self.total else 0.0


@dataclass(frozen=True)
class CaptureReuse:
    previous_snapshot_id: str = ""
    reused_nodes: int = 0
    reused_edges: int = 0
    reused_references: int = 0
    reused_dependencies: int = 0
    reused_unknown_plugins: int = 0
    topology_unchanged: bool = False


def _maya_modules():
    try:
        import maya.api.OpenMaya as om  # type: ignore
        import maya.cmds as cmds  # type: ignore
    except ImportError as exc:
        raise MayaUnavailableError("Maya Python modules are unavailable") from exc
    return om, cmds


def _safe(callable_, default=None):
    try:
        return callable_()
    except Exception:
        return default


def _uuid_for(fn: Any) -> str:
    value = _safe(lambda: fn.uuid().asString(), "")
    return str(value or "type-name:%s:%s" % (fn.typeName, fn.name()))


def _reference_file(cmds: Any, name: str, referenced: bool) -> str:
    if not referenced:
        return ""
    return str(_safe(lambda: cmds.referenceQuery(name, filename=True), "") or "")


def _reference_node(cmds: Any, name: str, referenced: bool) -> str:
    if not referenced:
        return ""
    return str(_safe(lambda: cmds.referenceQuery(name, referenceNode=True), "") or "")


def _first_text(value: Any) -> str:
    if isinstance(value, (tuple, list)):
        return str(value[0]) if value else ""
    return str(value or "")


def _scene_settings(om: Any, cmds: Any) -> SceneSettings:
    """Collect optional host preferences without making capture availability brittle."""

    seconds_per_frame = _safe(
        lambda: om.MTime(1.0, om.MTime.uiUnit()).asUnits(om.MTime.kSeconds),
        0.0,
    )
    fps = 1.0 / float(seconds_per_frame) if seconds_per_frame else 0.0
    color_enabled = _safe(
        lambda: cmds.colorManagementPrefs(query=True, cmEnabled=True), None
    )
    if color_enabled is not None:
        color_enabled = bool(color_enabled)
    return SceneSettings(
        time_unit=str(_safe(lambda: cmds.currentUnit(query=True, time=True), "") or ""),
        frames_per_second=fps,
        linear_unit=str(_safe(lambda: cmds.currentUnit(query=True, linear=True), "") or ""),
        angular_unit=str(_safe(lambda: cmds.currentUnit(query=True, angle=True), "") or ""),
        up_axis=str(_safe(lambda: cmds.upAxis(query=True, axis=True), "") or "").lower(),
        color_management_enabled=color_enabled,
        rendering_space=str(
            _safe(lambda: cmds.colorManagementPrefs(query=True, renderingSpaceName=True), "") or ""
        ),
        view_transform=str(
            _safe(lambda: cmds.colorManagementPrefs(query=True, viewTransformName=True), "") or ""
        ),
        color_config_path=str(
            _safe(lambda: cmds.colorManagementPrefs(query=True, configFilePath=True), "") or ""
        ),
    )


def _scene_lifecycle(cmds: Any) -> SceneLifecycle:
    modified = _safe(lambda: cmds.file(query=True, modified=True), None)
    if modified is not None:
        modified = bool(modified)
    return SceneLifecycle(
        modified=modified,
        file_type=_first_text(_safe(lambda: cmds.file(query=True, type=True), "")),
        workspace_root=str(
            _safe(lambda: cmds.workspace(query=True, rootDirectory=True), "") or ""
        ),
        current_time=float(_safe(lambda: cmds.currentTime(query=True), 0.0) or 0.0),
        playback_min=float(
            _safe(lambda: cmds.playbackOptions(query=True, minTime=True), 0.0) or 0.0
        ),
        playback_max=float(
            _safe(lambda: cmds.playbackOptions(query=True, maxTime=True), 0.0) or 0.0
        ),
        animation_start=float(
            _safe(lambda: cmds.playbackOptions(query=True, animationStartTime=True), 0.0)
            or 0.0
        ),
        animation_end=float(
            _safe(lambda: cmds.playbackOptions(query=True, animationEndTime=True), 0.0)
            or 0.0
        ),
    )


def _scene_references(cmds: Any, nodes: Iterable[SceneNode]) -> Tuple[SceneReference, ...]:
    ids_by_reference: Dict[str, List[str]] = {}
    for node in nodes:
        reference_node = str(node.metadata.get("reference_node", ""))
        if reference_node:
            ids_by_reference.setdefault(reference_node, []).append(node.id)

    records = []
    existence = {}
    for reference_node in tuple(_safe(lambda: cmds.ls(type="reference"), ()) or ()):
        resolved = str(
            _safe(lambda: cmds.referenceQuery(reference_node, filename=True), "") or ""
        )
        # Maya's process-wide sharedReferenceNode is not a file reference.
        if not resolved:
            continue
        unresolved = str(
            _safe(
                lambda: cmds.referenceQuery(
                    reference_node, filename=True, unresolvedName=True
                ),
                "",
            )
            or ""
        )
        canonical = str(
            _safe(
                lambda: cmds.referenceQuery(
                    reference_node, filename=True, withoutCopyNumber=True
                ),
                "",
            )
            or re.sub(r"\{\d+\}$", "", resolved)
        )
        copy_match = re.search(r"\{(\d+)\}$", resolved)
        copy_number = int(copy_match.group(1)) if copy_match else 0
        normalized = os.path.normcase(os.path.normpath(canonical)) if canonical else ""
        if normalized not in existence:
            if not canonical or _path_kind(canonical) == "network":
                existence[normalized] = None
            else:
                exists = _safe(
                    lambda canonical=canonical: cmds.file(
                        canonical, query=True, exists=True
                    ),
                    None,
                )
                existence[normalized] = bool(exists) if exists is not None else None
        namespace = str(
            _safe(lambda: cmds.referenceQuery(reference_node, namespace=True), "") or ""
        ).lstrip(":")
        parent_reference = _first_text(
            _safe(
                lambda: cmds.referenceQuery(
                    reference_node, parent=True, referenceNode=True
                ),
                "",
            )
        )
        failed = _safe(
            lambda: cmds.referenceQuery(
                reference_node, editStrings=True, failedEdits=True
            ),
            None,
        )
        failed_complete = failed is not None
        failed_edits = tuple(str(value) for value in (failed or ()))
        records.append(
            SceneReference(
                reference_node=str(reference_node),
                resolved_path=resolved,
                unresolved_path=unresolved,
                canonical_path=canonical,
                copy_number=copy_number,
                exists=existence[normalized],
                namespace=namespace,
                parent_reference_node=parent_reference,
                loaded=bool(
                    _safe(
                        lambda: cmds.referenceQuery(reference_node, isLoaded=True),
                        False,
                    )
                ),
                preview_only=bool(
                    _safe(
                        lambda: cmds.referenceQuery(reference_node, isPreviewOnly=True),
                        False,
                    )
                ),
                node_ids=tuple(sorted(ids_by_reference.get(str(reference_node), ()))),
                failed_edit_count=len(failed_edits),
                failed_edit_samples=tuple(value[:500] for value in failed_edits[:12]),
                failed_edit_scan_complete=failed_complete,
            )
        )
    return tuple(sorted(records, key=lambda item: item.reference_node))


def _unknown_plugins(cmds: Any) -> Tuple[UnknownPlugin, ...]:
    """Read Maya's serialized missing plug-in registry without loading anything."""

    names = tuple(
        sorted(
            str(value)
            for value in (_safe(lambda: cmds.unknownPlugin(query=True, list=True), ()) or ())
        )
    )
    records = []
    for name in names:
        node_types = tuple(
            sorted(
                str(value)
                for value in (
                    _safe(lambda name=name: cmds.unknownPlugin(name, query=True, nodeTypes=True), ())
                    or ()
                )
            )
        )
        data_types = tuple(
            sorted(
                str(value)
                for value in (
                    _safe(lambda name=name: cmds.unknownPlugin(name, query=True, dataTypes=True), ())
                    or ()
                )
            )
        )
        version = str(
            _safe(lambda name=name: cmds.unknownPlugin(name, query=True, version=True), "")
            or ""
        )
        records.append(UnknownPlugin(name, version, node_types, data_types))
    return tuple(records)


_SEQUENCE_TOKEN = re.compile(r"(<udim>|<uvtile>|<f>|#+|%0\d+d)", re.IGNORECASE)


def _dependency_kind(node_type: str, attribute: str) -> str:
    node_type_lower = node_type.lower()
    attribute_lower = attribute.lower()
    if node_type_lower == "file" or "texture" in attribute_lower:
        return "texture"
    if node_type_lower == "audio":
        return "audio"
    if node_type_lower == "imageplane":
        return "image-plane"
    if "alembic" in node_type_lower or attribute_lower.endswith("abc_file"):
        return "alembic"
    if "usd" in node_type_lower:
        return "usd"
    if node_type_lower == "gpucache":
        return "gpu-cache"
    if "standin" in node_type_lower or attribute_lower.endswith(".dso"):
        return "stand-in"
    if "cache" in node_type_lower:
        return "cache"
    return "external-file"


def _path_kind(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/")
    if normalized.startswith("//"):
        return "network"
    if re.match(r"^[A-Za-z]:/", normalized):
        return "absolute"
    if "$" in raw_path or re.search(r"%[^%]+%", raw_path):
        return "environment"
    return "workspace-relative" if raw_path else "unknown"


def _inside_workspace(resolved_path: str, workspace_root: str) -> bool | None:
    if not resolved_path or not workspace_root:
        return None
    try:
        path = os.path.normcase(os.path.abspath(resolved_path))
        root = os.path.normcase(os.path.abspath(workspace_root))
        return os.path.commonpath((path, root)) == root
    except (OSError, ValueError):
        return False


def _external_dependencies(cmds: Any, nodes: Iterable[SceneNode]) -> Tuple[ExternalDependency, ...]:
    """Read Maya's registered path inventory; never recurse or open dependency files."""

    nodes = tuple(nodes)
    identities: Dict[str, List[SceneNode]] = {}
    for node in nodes:
        for identity in (node.name,) + node.dag_paths:
            identities.setdefault(identity, []).append(node)
    workspace_root = str(
        _safe(lambda: cmds.workspace(query=True, rootDirectory=True), "") or ""
    )
    directories = tuple(
        _safe(lambda: cmds.filePathEditor(query=True, listDirectories=""), ()) or ()
    )
    result: Dict[str, ExternalDependency] = {}
    for directory in directories:
        entries = tuple(
            _safe(
                lambda directory=directory: cmds.filePathEditor(
                    query=True,
                    listFiles=str(directory),
                    withAttribute=True,
                    status=True,
                ),
                (),
            )
            or ()
        )
        for index in range(0, len(entries) - 2, 3):
            filename, plug, status = map(str, entries[index:index + 3])
            owner_name = plug.split(".", 1)[0]
            candidates = identities.get(owner_name, ())
            if len(candidates) != 1:
                long_names = tuple(_safe(lambda: cmds.ls(owner_name, long=True), ()) or ())
                matched = {
                    candidate.id: candidate
                    for long_name in long_names
                    for candidate in identities.get(str(long_name), ())
                }
                candidates = tuple(matched.values())
            if len(candidates) != 1:
                continue
            node = candidates[0]
            if node.type_name == "reference":
                continue
            raw_path = str(_safe(lambda plug=plug: cmds.getAttr(plug), "") or "")
            resolved_path = os.path.normpath(os.path.join(str(directory), filename))
            dependency_id = "external:%s" % hashlib.sha1(
                (node.id + "|" + plug).encode("utf-8")
            ).hexdigest()[:16]
            token = _SEQUENCE_TOKEN.search(raw_path) or _SEQUENCE_TOKEN.search(filename)
            path_kind = _path_kind(raw_path)
            inventory = inspect_local_sequence(
                resolved_path,
                token.group(0) if token else "",
                path_kind=path_kind,
            )
            exists = status not in {"0", "false", "False"}
            if token and inventory.member_count:
                exists = True
            elif token and inventory.scan_complete:
                exists = False
            result[dependency_id] = ExternalDependency(
                id=dependency_id,
                node_id=node.id,
                node_name=node.name,
                node_type=node.type_name,
                attribute=plug,
                kind=_dependency_kind(node.type_name, plug),
                raw_path=raw_path,
                resolved_path=resolved_path,
                exists=exists,
                path_kind=path_kind,
                inside_workspace=_inside_workspace(resolved_path, workspace_root),
                sequence_pattern=token.group(0) if token else "",
                sequence_kind=inventory.kind,
                sequence_member_count=inventory.member_count,
                sequence_expected_count=inventory.expected_count,
                sequence_missing_count=inventory.missing_count,
                sequence_missing_samples=inventory.missing_samples,
                sequence_scan_complete=inventory.scan_complete,
                sequence_scan_reason=inventory.scan_reason,
            )
    return tuple(sorted(result.values(), key=lambda item: item.id))


def _host_context_signature(om: Any, cmds: Any):
    """Cheap Maya-owned state whose drift would make one snapshot internally mixed."""

    _safe(lambda: cmds.filePathEditor(refresh=True), None)
    path_inventory = []
    directories = tuple(
        _safe(lambda: cmds.filePathEditor(query=True, listDirectories=""), ()) or ()
    )
    for directory in sorted(str(value) for value in directories):
        entries = tuple(
            str(value)
            for value in (
                _safe(
                    lambda directory=directory: cmds.filePathEditor(
                        query=True,
                        listFiles=directory,
                        withAttribute=True,
                        status=True,
                    ),
                    (),
                )
                or ()
            )
        )
        path_inventory.append((directory, entries))
    plugins = tuple(
        sorted(
            str(value)
            for value in (
                _safe(lambda: cmds.pluginInfo(query=True, pluginsInUse=True), ()) or ()
            )
        )
    )
    return (
        _scene_settings(om, cmds),
        _scene_lifecycle(cmds),
        plugins,
        _unknown_plugins(cmds),
        tuple(path_inventory),
    )


def _host_context_changes(before, after) -> Tuple[str, ...]:
    labels = (
        "场景设置",
        "场景生命周期",
        "插件清单",
        "缺失插件清单",
        "外部文件清单",
    )
    changes = list(
        label for label, old, current in zip(labels, before, after) if old != current
    )
    if before[1] != after[1]:
        lifecycle_fields = (
            "modified",
            "file_type",
            "workspace_root",
            "current_time",
            "playback_min",
            "playback_max",
            "animation_start",
            "animation_end",
        )
        changed_fields = tuple(
            field
            for field in lifecycle_fields
            if getattr(before[1], field) != getattr(after[1], field)
        )
        changes[changes.index("场景生命周期")] = "场景生命周期.%s" % "/".join(
            changed_fields
        )
    return tuple(changes)


def _namespace(name: str) -> str:
    leaf = name.rsplit("|", 1)[-1]
    return leaf.rsplit(":", 1)[0] if ":" in leaf else ""


def _dag_paths(om: Any, obj: Any) -> Tuple[str, ...]:
    if not obj.hasFn(om.MFn.kDagNode):
        return ()
    fn = om.MFnDagNode(obj)
    paths = _safe(lambda: fn.getAllPaths(), ()) or ()
    return tuple(sorted(path.fullPathName() for path in paths))


def _is_message_plug(om: Any, plug: Any) -> bool:
    """Message links carry ownership metadata, not evaluation causality."""
    attribute = _safe(lambda: plug.attribute(), None)
    return bool(attribute is not None and _safe(lambda: attribute.hasFn(om.MFn.kMessageAttribute), False))


class MayaSceneCaptureSession:
    """Main-thread, time-sliced snapshot capture with topology mutation guards."""

    STAGE_LABELS = {
        "nodes": "正在读取稳定节点身份",
        "dg": "正在追踪依赖连接",
        "dag": "正在映射层级结构",
        "verify": "正在验证场景保持稳定",
        "finalize": "正在封存不可变快照",
        "done": "快照已封存",
    }

    def __init__(self, previous_snapshot: Optional[SceneSnapshot] = None):
        self.om, self.cmds = _maya_modules()
        self.previous_snapshot = previous_snapshot
        self.stage = "nodes"
        self.nodes: List[SceneNode] = []
        self.object_by_id: Dict[str, Any] = {}
        self.id_by_hash: Dict[int, str] = {}
        self.edges: List[SceneEdge] = []
        self.edge_keys: Set[Tuple[str, str, str, str, str]] = set()
        self._iterator = self.om.MItDependencyNodes()
        self._ordered_ids: Tuple[str, ...] = ()
        self._index = 0
        self._verify_identities = set()
        self._cancelled = False
        self._topology_changed = False
        self._callbacks = []
        self._result: Optional[SceneSnapshot] = None
        self._reuse = CaptureReuse()
        self._scene_path = str(
            _safe(lambda: self.cmds.file(query=True, sceneName=True), "") or ""
        )
        self._initial_host_context = _host_context_signature(self.om, self.cmds)
        self._install_mutation_guards()

    def _install_mutation_guards(self) -> None:
        def changed(*_args):
            self._topology_changed = True

        for register in (
            lambda: self.om.MDGMessage.addNodeAddedCallback(changed, "dependNode"),
            lambda: self.om.MDGMessage.addNodeRemovedCallback(changed, "dependNode"),
            lambda: self.om.MDGMessage.addConnectionCallback(changed),
        ):
            try:
                callback = register()
            except Exception as exc:
                self._remove_mutation_guards()
                raise RuntimeError(
                    "Could not install capture mutation guard: %s" % exc
                ) from exc
            self._callbacks.append(callback)

    def _remove_mutation_guards(self) -> None:
        if self._callbacks:
            _safe(lambda: self.om.MMessage.removeCallbacks(self._callbacks), None)
            self._callbacks = []

    def __del__(self):
        self._remove_mutation_guards()

    @property
    def done(self) -> bool:
        return self.stage == "done"

    @property
    def result(self) -> SceneSnapshot:
        if self._result is None:
            raise RuntimeError("Capture session has not completed")
        return self._result

    @property
    def reuse(self) -> CaptureReuse:
        return self._reuse

    def cancel(self) -> None:
        self._cancelled = True

    def _check_guard(self) -> None:
        if self._cancelled:
            self._remove_mutation_guards()
            raise CaptureCancelled("Scene capture cancelled")
        current_path = str(
            _safe(lambda: self.cmds.file(query=True, sceneName=True), "") or ""
        )
        if self._topology_changed or current_path != self._scene_path:
            self._remove_mutation_guards()
            raise SceneChangedDuringCapture(
                "Scene topology or file identity changed during capture; retry on a stable scene"
            )

    def _add_edge(self, edge: SceneEdge) -> None:
        key = (
            edge.source_id,
            edge.target_id,
            edge.relation,
            edge.source_plug,
            edge.target_plug,
        )
        if key not in self.edge_keys:
            self.edge_keys.add(key)
            self.edges.append(edge)

    def _step_node(self) -> None:
        if self._iterator.isDone():
            self._ordered_ids = tuple(self.object_by_id)
            self._index = 0
            self.stage = "dg"
            return
        obj = self._iterator.thisNode()
        fn = self.om.MFnDependencyNode(obj)
        node_id = _uuid_for(fn)
        name = str(fn.name())
        referenced = bool(_safe(lambda: fn.isFromReferencedFile, False))
        reference_node = _reference_node(self.cmds, name, referenced)
        paths = _dag_paths(self.om, obj)
        # MFnDependencyNode already owns the lock bit. Crossing through cmds for
        # every node turns a time-sliced capture into an N-command bottleneck on
        # real production scenes (1,200 nodes measured >99 s in Maya 2025).
        locked = bool(_safe(lambda: fn.isLocked, False))
        type_name = str(fn.typeName)
        metadata = {"locked": locked, "reference_node": reference_node}
        if type_name in {"unknown", "unknownDag", "unknownTransform"}:
            metadata.update(
                unknown_plugin=str(
                    _safe(lambda: self.cmds.unknownNode(name, query=True, plugin=True), "")
                    or ""
                ),
                unknown_real_class=str(
                    _safe(
                        lambda: self.cmds.unknownNode(name, query=True, realClassName=True),
                        "",
                    )
                    or ""
                ),
            )
        self.nodes.append(
            SceneNode(
                id=node_id,
                name=name,
                type_name=type_name,
                dag_paths=paths,
                is_dag=bool(paths),
                referenced=referenced,
                reference_file=_reference_file(self.cmds, name, referenced),
                namespace=_namespace(name),
                metadata=metadata,
            )
        )
        self.object_by_id[node_id] = obj
        self.id_by_hash[int(self.om.MObjectHandle(obj).hashCode())] = node_id
        self._iterator.next()

    def _step_dg(self) -> None:
        if self._index >= len(self._ordered_ids):
            self._index = 0
            self.stage = "dag"
            return
        target_id = self._ordered_ids[self._index]
        self._index += 1
        obj = self.object_by_id[target_id]
        fn = self.om.MFnDependencyNode(obj)
        for target_plug in _safe(lambda: fn.getConnections(), ()) or ():
            if not bool(_safe(lambda: target_plug.isDestination, False)):
                continue
            source_plug = _safe(lambda: target_plug.source(), None)
            if source_plug is None or bool(_safe(lambda: source_plug.isNull, True)):
                continue
            if _is_message_plug(self.om, source_plug) or _is_message_plug(
                self.om, target_plug
            ):
                continue
            source_obj = _safe(lambda: source_plug.node(), None)
            if source_obj is None:
                continue
            source_id = self.id_by_hash.get(
                int(self.om.MObjectHandle(source_obj).hashCode())
            )
            if source_id:
                self._add_edge(
                    SceneEdge(
                        source_id=source_id,
                        target_id=target_id,
                        relation="dg",
                        source_plug=str(_safe(lambda: source_plug.name(), "")),
                        target_plug=str(_safe(lambda: target_plug.name(), "")),
                    )
                )

    def _step_dag(self) -> None:
        if self._index >= len(self._ordered_ids):
            self._iterator = self.om.MItDependencyNodes()
            self._index = 0
            self.stage = "verify"
            return
        child_id = self._ordered_ids[self._index]
        self._index += 1
        obj = self.object_by_id[child_id]
        if not obj.hasFn(self.om.MFn.kDagNode):
            return
        dag_fn = self.om.MFnDagNode(obj)
        for index in range(int(_safe(lambda: dag_fn.parentCount(), 0) or 0)):
            parent_obj = _safe(lambda index=index: dag_fn.parent(index), None)
            if parent_obj is None or parent_obj.apiType() == self.om.MFn.kWorld:
                continue
            parent_id = self.id_by_hash.get(
                int(self.om.MObjectHandle(parent_obj).hashCode())
            )
            if parent_id:
                self._add_edge(SceneEdge(parent_id, child_id, relation="dag"))

    def _step_verify(self) -> None:
        if self._iterator.isDone():
            expected = {(node.id, node.name, node.type_name) for node in self.nodes}
            if self._verify_identities != expected:
                self._remove_mutation_guards()
                raise SceneChangedDuringCapture(
                    "Scene node identity changed during capture; retry on a stable scene"
                )
            self.stage = "finalize"
            return
        obj = self._iterator.thisNode()
        fn = self.om.MFnDependencyNode(obj)
        self._verify_identities.add((_uuid_for(fn), str(fn.name()), str(fn.typeName)))
        self._iterator.next()

    def _finalize(self) -> None:
        self._check_guard()
        final_host_context = _host_context_signature(self.om, self.cmds)
        if final_host_context != self._initial_host_context:
            self._remove_mutation_guards()
            changed = _host_context_changes(
                self._initial_host_context, final_host_context
            )
            raise SceneChangedDuringCapture(
                "采集期间%s发生变化；本次部分快照未提交，请在场景稳定后重试"
                % "、".join(changed or ("宿主上下文",))
            )
        plugins = tuple(
            _safe(lambda: self.cmds.pluginInfo(query=True, pluginsInUse=True), ()) or ()
        )
        selection = tuple(
            _safe(lambda: self.cmds.ls(selection=True, long=True), ()) or ()
        )
        references = _scene_references(self.cmds, self.nodes)
        unknown_plugins = _unknown_plugins(self.cmds)
        dependencies = _external_dependencies(self.cmds, self.nodes)
        nodes = tuple(self.nodes)
        edges = tuple(self.edges)
        previous = self.previous_snapshot
        reused_nodes = reused_edges = reused_references = reused_dependencies = 0
        reused_unknown_plugins = 0
        topology_unchanged = False
        if previous is not None:
            previous_nodes = previous.node_map
            nodes = tuple(
                previous_nodes[node.id]
                if node.id in previous_nodes and previous_nodes[node.id] == node
                else node
                for node in nodes
            )
            reused_nodes = sum(
                node.id in previous_nodes and node is previous_nodes[node.id]
                for node in nodes
            )
            same_node_order = tuple(node.id for node in nodes) == tuple(
                node.id for node in previous.nodes
            )
            if same_node_order and edges == previous.edges:
                edges = previous.edges
                reused_edges = len(edges)
                topology_unchanged = True
            previous_references = {
                reference.reference_node: reference
                for reference in previous.references
            }
            references = tuple(
                previous_references[reference.reference_node]
                if reference.reference_node in previous_references
                and previous_references[reference.reference_node] == reference
                else reference
                for reference in references
            )
            reused_references = sum(
                reference.reference_node in previous_references
                and reference is previous_references[reference.reference_node]
                for reference in references
            )
            previous_dependencies = {
                dependency.id: dependency
                for dependency in previous.external_dependencies
            }
            dependencies = tuple(
                previous_dependencies[dependency.id]
                if dependency.id in previous_dependencies
                and previous_dependencies[dependency.id] == dependency
                else dependency
                for dependency in dependencies
            )
            reused_dependencies = sum(
                dependency.id in previous_dependencies
                and dependency is previous_dependencies[dependency.id]
                for dependency in dependencies
            )
            if unknown_plugins == previous.unknown_plugins:
                unknown_plugins = previous.unknown_plugins
                reused_unknown_plugins = len(unknown_plugins)
            self._reuse = CaptureReuse(
                previous_snapshot_id=previous.snapshot_id,
                reused_nodes=reused_nodes,
                reused_edges=reused_edges,
                reused_references=reused_references,
                reused_dependencies=reused_dependencies,
                reused_unknown_plugins=reused_unknown_plugins,
                topology_unchanged=topology_unchanged,
            )
        self._result = SceneSnapshot.build(
            nodes,
            edges,
            references,
            dependencies,
            unknown_plugins=unknown_plugins,
            source_scene=self._scene_path,
            maya_version=str(_safe(lambda: self.cmds.about(version=True), "")),
            scene_settings=_scene_settings(self.om, self.cmds),
            scene_lifecycle=_scene_lifecycle(self.cmds),
            metadata={
                "plugins_in_use": plugins,
                "selection": selection,
                "capture_reuse": {
                    "previous_snapshot_id": self._reuse.previous_snapshot_id,
                    "reused_nodes": self._reuse.reused_nodes,
                    "reused_edges": self._reuse.reused_edges,
                    "reused_references": self._reuse.reused_references,
                    "reused_dependencies": self._reuse.reused_dependencies,
                    "reused_unknown_plugins": self._reuse.reused_unknown_plugins,
                    "topology_unchanged": self._reuse.topology_unchanged,
                },
            },
        )
        self.stage = "done"
        self._remove_mutation_guards()

    def progress(self) -> CaptureProgress:
        if self.stage == "nodes":
            completed, total = len(self.nodes), 0
        elif self.stage in {"dg", "dag"}:
            completed, total = self._index, len(self._ordered_ids)
        elif self.stage == "verify":
            completed, total = len(self._verify_identities), len(self.nodes)
        else:
            completed = total = len(self.nodes)
        return CaptureProgress(
            self.stage,
            completed,
            total,
            self.STAGE_LABELS[self.stage],
        )

    def step(self, *, max_items: int = 256, max_milliseconds: float = 8.0) -> CaptureProgress:
        if max_items < 1 or max_milliseconds <= 0:
            raise ValueError("Capture slice budget must be positive")
        self._check_guard()
        deadline = time.perf_counter() + max_milliseconds / 1000.0
        processed = 0
        while not self.done and processed < max_items and time.perf_counter() < deadline:
            self._check_guard()
            if self.stage == "nodes":
                self._step_node()
            elif self.stage == "dg":
                self._step_dg()
            elif self.stage == "dag":
                self._step_dag()
            elif self.stage == "verify":
                self._step_verify()
            elif self.stage == "finalize":
                self._finalize()
            processed += 1
        return self.progress()


def capture_scene(previous_snapshot: Optional[SceneSnapshot] = None) -> SceneSnapshot:
    """Synchronous adapter over the production time-sliced collector."""
    session = MayaSceneCaptureSession(previous_snapshot=previous_snapshot)
    while not session.done:
        session.step(max_items=2048, max_milliseconds=1000.0)
    return session.result
