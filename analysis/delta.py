"""Stable-identity structural diff for SceneSnapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Tuple

from ..model import ExternalDependency, SceneEdge, SceneNode, SceneReference, SceneSnapshot


@dataclass(frozen=True)
class NodeChange:
    node_id: str
    kind: str
    before_name: str = ""
    after_name: str = ""
    changed_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EdgeChange:
    kind: str
    source_id: str
    target_id: str
    relation: str
    source_plug: str = ""
    target_plug: str = ""


@dataclass(frozen=True)
class RewireChange:
    target_id: str
    target_plug: str
    relation: str
    old_source_id: str
    new_source_id: str
    old_source_plug: str = ""
    new_source_plug: str = ""


@dataclass(frozen=True)
class ReferenceChange:
    reference_node: str
    kind: str
    before_path: str = ""
    after_path: str = ""
    changed_fields: Tuple[str, ...] = ()
    node_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ExternalDependencyChange:
    dependency_id: str
    node_id: str
    kind: str
    before_path: str = ""
    after_path: str = ""
    changed_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class UnknownPluginChange:
    plugin_name: str
    kind: str
    changed_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneDelta:
    before_snapshot_id: str
    after_snapshot_id: str
    node_changes: Tuple[NodeChange, ...]
    edge_changes: Tuple[EdgeChange, ...]
    rewires: Tuple[RewireChange, ...]
    reference_changes: Tuple[ReferenceChange, ...] = ()
    setting_changes: Tuple[str, ...] = ()
    external_dependency_changes: Tuple[ExternalDependencyChange, ...] = ()
    unknown_plugin_changes: Tuple[UnknownPluginChange, ...] = ()
    lifecycle_changes: Tuple[str, ...] = ()

    @property
    def changed_node_ids(self) -> Tuple[str, ...]:
        ids = {change.node_id for change in self.node_changes}
        for change in self.edge_changes:
            ids.update((change.source_id, change.target_id))
        for rewire in self.rewires:
            ids.update((rewire.old_source_id, rewire.new_source_id, rewire.target_id))
        for change in self.reference_changes:
            ids.update(change.node_ids)
        ids.update(change.node_id for change in self.external_dependency_changes)
        return tuple(sorted(ids))

    def summary(self) -> Dict[str, int]:
        return {
            "nodes_added": sum(change.kind == "added" for change in self.node_changes),
            "nodes_removed": sum(change.kind == "removed" for change in self.node_changes),
            "nodes_modified": sum(change.kind not in {"added", "removed"} for change in self.node_changes),
            "edges_added": sum(change.kind == "added" for change in self.edge_changes),
            "edges_removed": sum(change.kind == "removed" for change in self.edge_changes),
            "rewires": len(self.rewires),
            "references_added": sum(change.kind == "added" for change in self.reference_changes),
            "references_removed": sum(change.kind == "removed" for change in self.reference_changes),
            "references_modified": sum(change.kind == "modified" for change in self.reference_changes),
            "scene_settings_modified": len(self.setting_changes),
            "external_dependencies_added": sum(
                change.kind == "added" for change in self.external_dependency_changes
            ),
            "external_dependencies_removed": sum(
                change.kind == "removed" for change in self.external_dependency_changes
            ),
            "external_dependencies_modified": sum(
                change.kind == "modified" for change in self.external_dependency_changes
            ),
            "unknown_plugins_added": sum(
                change.kind == "added" for change in self.unknown_plugin_changes
            ),
            "unknown_plugins_removed": sum(
                change.kind == "removed" for change in self.unknown_plugin_changes
            ),
            "unknown_plugins_modified": sum(
                change.kind == "modified" for change in self.unknown_plugin_changes
            ),
            "scene_lifecycle_modified": len(self.lifecycle_changes),
        }

    @property
    def is_empty(self) -> bool:
        return not (
            self.node_changes or self.edge_changes or self.rewires or self.reference_changes
            or self.setting_changes
            or self.external_dependency_changes
            or self.unknown_plugin_changes
            or self.lifecycle_changes
        )


NODE_FIELDS = (
    "name",
    "type_name",
    "dag_paths",
    "is_dag",
    "referenced",
    "reference_file",
    "namespace",
    "metadata",
)

REFERENCE_FIELDS = (
    "resolved_path",
    "unresolved_path",
    "canonical_path",
    "copy_number",
    "exists",
    "namespace",
    "parent_reference_node",
    "loaded",
    "preview_only",
    "failed_edit_count",
    "failed_edit_samples",
    "failed_edit_scan_complete",
)

EXTERNAL_DEPENDENCY_FIELDS = (
    "kind",
    "raw_path",
    "resolved_path",
    "exists",
    "path_kind",
    "inside_workspace",
    "sequence_pattern",
    "sequence_kind",
    "sequence_member_count",
    "sequence_expected_count",
    "sequence_missing_count",
    "sequence_missing_samples",
    "sequence_scan_complete",
    "sequence_scan_reason",
)

UNKNOWN_PLUGIN_FIELDS = ("version", "node_types", "data_types")


def _unknown_plugin_changes(
    before: SceneSnapshot, after: SceneSnapshot
) -> Tuple[UnknownPluginChange, ...]:
    old = {item.name: item for item in before.unknown_plugins}
    new = {item.name: item for item in after.unknown_plugins}
    changes = [UnknownPluginChange(name, "removed") for name in sorted(old.keys() - new.keys())]
    changes.extend(
        UnknownPluginChange(name, "added") for name in sorted(new.keys() - old.keys())
    )
    for name in sorted(old.keys() & new.keys()):
        fields = tuple(
            field
            for field in UNKNOWN_PLUGIN_FIELDS
            if getattr(old[name], field) != getattr(new[name], field)
        )
        if fields:
            changes.append(UnknownPluginChange(name, "modified", fields))
    return tuple(changes)


def _external_dependency_changes(
    before: SceneSnapshot, after: SceneSnapshot
) -> Tuple[ExternalDependencyChange, ...]:
    old = {item.id: item for item in before.external_dependencies}
    new = {item.id: item for item in after.external_dependencies}
    changes = []
    for dependency_id in sorted(old.keys() - new.keys()):
        item = old[dependency_id]
        changes.append(
            ExternalDependencyChange(
                dependency_id, item.node_id, "removed", before_path=item.raw_path
            )
        )
    for dependency_id in sorted(new.keys() - old.keys()):
        item = new[dependency_id]
        changes.append(
            ExternalDependencyChange(
                dependency_id, item.node_id, "added", after_path=item.raw_path
            )
        )
    for dependency_id in sorted(old.keys() & new.keys()):
        previous, current = old[dependency_id], new[dependency_id]
        fields = tuple(
            field
            for field in EXTERNAL_DEPENDENCY_FIELDS
            if getattr(previous, field) != getattr(current, field)
        )
        if fields:
            changes.append(
                ExternalDependencyChange(
                    dependency_id,
                    current.node_id,
                    "modified",
                    before_path=previous.raw_path,
                    after_path=current.raw_path,
                    changed_fields=fields,
                )
            )
    return tuple(changes)


def _reference_changes(
    before: SceneSnapshot, after: SceneSnapshot
) -> Tuple[ReferenceChange, ...]:
    if before.references is after.references:
        return ()
    old = {reference.reference_node: reference for reference in before.references}
    new = {reference.reference_node: reference for reference in after.references}
    changes = []
    for name in sorted(old.keys() - new.keys()):
        changes.append(
            ReferenceChange(
                name,
                "removed",
                before_path=old[name].resolved_path,
                node_ids=old[name].node_ids,
            )
        )
    for name in sorted(new.keys() - old.keys()):
        changes.append(
            ReferenceChange(
                name,
                "added",
                after_path=new[name].resolved_path,
                node_ids=new[name].node_ids,
            )
        )
    for name in sorted(old.keys() & new.keys()):
        fields = tuple(
            field for field in REFERENCE_FIELDS
            if getattr(old[name], field) != getattr(new[name], field)
        )
        if fields:
            changes.append(
                ReferenceChange(
                    reference_node=name,
                    kind="modified",
                    before_path=old[name].resolved_path,
                    after_path=new[name].resolved_path,
                    changed_fields=fields,
                    node_ids=tuple(sorted(set(old[name].node_ids) | set(new[name].node_ids))),
                )
            )
    return tuple(changes)


def _edge_key(edge: SceneEdge) -> Tuple[str, str, str, str, str]:
    return (
        edge.source_id,
        edge.target_id,
        edge.relation,
        edge.source_plug,
        edge.target_plug,
    )


def _edge_change(kind: str, key: Tuple[str, str, str, str, str]) -> EdgeChange:
    source_id, target_id, relation, source_plug, target_plug = key
    return EdgeChange(kind, source_id, target_id, relation, source_plug, target_plug)


def _node_changes(before: SceneSnapshot, after: SceneSnapshot) -> Tuple[NodeChange, ...]:
    before_nodes, after_nodes = before.node_map, after.node_map
    changes = []
    for node_id in sorted(before_nodes.keys() - after_nodes.keys()):
        node = before_nodes[node_id]
        changes.append(NodeChange(node_id, "removed", before_name=node.name))
    for node_id in sorted(after_nodes.keys() - before_nodes.keys()):
        node = after_nodes[node_id]
        changes.append(NodeChange(node_id, "added", after_name=node.name))
    for node_id in sorted(before_nodes.keys() & after_nodes.keys()):
        old, new = before_nodes[node_id], after_nodes[node_id]
        fields = tuple(field for field in NODE_FIELDS if getattr(old, field) != getattr(new, field))
        if not fields:
            continue
        identity_fields = {"name", "dag_paths", "namespace"}
        kind = "renamed" if set(fields).issubset(identity_fields) else "modified"
        changes.append(
            NodeChange(
                node_id=node_id,
                kind=kind,
                before_name=old.name,
                after_name=new.name,
                changed_fields=fields,
            )
        )
    return tuple(changes)


def _edge_changes(
    before: SceneSnapshot, after: SceneSnapshot
) -> Tuple[Tuple[EdgeChange, ...], Tuple[RewireChange, ...]]:
    if before.edges is after.edges:
        return (), ()
    before_keys = {_edge_key(edge) for edge in before.edges}
    after_keys = {_edge_key(edge) for edge in after.edges}
    removed = before_keys - after_keys
    added = after_keys - before_keys

    # A stable target plug changing its source is a rewire, not unrelated delete/add noise.
    def target_key(key):
        return key[1], key[4], key[2]

    removed_by_target: Dict[Tuple[str, str, str], list] = {}
    added_by_target: Dict[Tuple[str, str, str], list] = {}
    for key in removed:
        if key[4]:
            removed_by_target.setdefault(target_key(key), []).append(key)
    for key in added:
        if key[4]:
            added_by_target.setdefault(target_key(key), []).append(key)

    rewires = []
    consumed_removed = set()
    consumed_added = set()
    for target in sorted(removed_by_target.keys() & added_by_target.keys()):
        old_keys = sorted(removed_by_target[target])
        new_keys = sorted(added_by_target[target])
        for old_key, new_key in zip(old_keys, new_keys):
            if old_key[0] == new_key[0] and old_key[3] == new_key[3]:
                continue
            consumed_removed.add(old_key)
            consumed_added.add(new_key)
            rewires.append(
                RewireChange(
                    target_id=target[0],
                    target_plug=target[1],
                    relation=target[2],
                    old_source_id=old_key[0],
                    new_source_id=new_key[0],
                    old_source_plug=old_key[3],
                    new_source_plug=new_key[3],
                )
            )

    changes = tuple(
        [_edge_change("removed", key) for key in sorted(removed - consumed_removed)]
        + [_edge_change("added", key) for key in sorted(added - consumed_added)]
    )
    return changes, tuple(rewires)


def compare_snapshots(before: SceneSnapshot, after: SceneSnapshot) -> SceneDelta:
    """Compare two snapshots without relying on mutable Maya names."""
    edge_changes, rewires = _edge_changes(before, after)
    return SceneDelta(
        before_snapshot_id=before.snapshot_id,
        after_snapshot_id=after.snapshot_id,
        node_changes=_node_changes(before, after),
        edge_changes=edge_changes,
        rewires=rewires,
        reference_changes=_reference_changes(before, after),
        setting_changes=tuple(
            field
            for field in before.scene_settings.__dataclass_fields__
            if getattr(before.scene_settings, field) != getattr(after.scene_settings, field)
        ),
        external_dependency_changes=_external_dependency_changes(before, after),
        unknown_plugin_changes=_unknown_plugin_changes(before, after),
        lifecycle_changes=tuple(
            field
            for field in before.scene_lifecycle.__dataclass_fields__
            if getattr(before.scene_lifecycle, field)
            != getattr(after.scene_lifecycle, field)
        ),
    )
