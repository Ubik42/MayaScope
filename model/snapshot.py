"""Serializable, immutable representation of a Maya scene.

This module intentionally has no Maya or Qt imports.  It is the boundary between
host collection and every analysis/visualisation consumer in MayaScope.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, Iterable, Mapping, Tuple
from uuid import uuid4

from ..schema import MigrationRegistry, SchemaMigrationError


SCHEMA_VERSION = 8
SNAPSHOT_MIGRATIONS = MigrationRegistry("SceneSnapshot", SCHEMA_VERSION)


@SNAPSHOT_MIGRATIONS.register(1)
def _snapshot_v1_to_v2(payload):
    payload["schema_version"] = 2
    payload.setdefault("references", [])
    payload.setdefault("metadata", {})
    return payload


@SNAPSHOT_MIGRATIONS.register(2)
def _snapshot_v2_to_v3(payload):
    payload["schema_version"] = 3
    payload.setdefault("scene_settings", {})
    return payload


@SNAPSHOT_MIGRATIONS.register(3)
def _snapshot_v3_to_v4(payload):
    payload["schema_version"] = 4
    payload.setdefault("external_dependencies", [])
    return payload


@SNAPSHOT_MIGRATIONS.register(4)
def _snapshot_v4_to_v5(payload):
    payload["schema_version"] = 5
    payload.setdefault("scene_lifecycle", {})
    return payload


@SNAPSHOT_MIGRATIONS.register(5)
def _snapshot_v5_to_v6(payload):
    payload["schema_version"] = 6
    payload.setdefault("unknown_plugins", [])
    return payload


@SNAPSHOT_MIGRATIONS.register(6)
def _snapshot_v6_to_v7(payload):
    payload["schema_version"] = 7
    for reference in payload.get("references", []):
        resolved = str(reference.get("resolved_path", ""))
        match = re.search(r"\{(\d+)\}$", resolved)
        reference.setdefault(
            "canonical_path", resolved[: match.start()] if match else resolved
        )
        reference.setdefault("copy_number", int(match.group(1)) if match else 0)
        reference.setdefault("exists", None)
    return payload


@SNAPSHOT_MIGRATIONS.register(7)
def _snapshot_v7_to_v8(payload):
    payload["schema_version"] = 8
    for dependency in payload.get("external_dependencies", []):
        dependency.setdefault("sequence_kind", "")
        dependency.setdefault("sequence_member_count", 0)
        dependency.setdefault("sequence_expected_count", None)
        dependency.setdefault("sequence_missing_count", None)
        dependency.setdefault("sequence_missing_samples", [])
        dependency.setdefault("sequence_scan_complete", False)
        dependency.setdefault("sequence_scan_reason", "旧版快照未采集序列成员")
    return payload


class SnapshotValidationError(ValueError):
    """Raised when a snapshot violates the graph data contract."""


def _freeze_mapping(value: Mapping[str, Any] | None) -> Dict[str, Any]:
    # A defensive shallow copy prevents collectors from mutating stored metadata.
    return dict(value or {})


@dataclass(frozen=True)
class SceneNode:
    id: str
    name: str
    type_name: str
    dag_paths: Tuple[str, ...] = ()
    is_dag: bool = False
    referenced: bool = False
    reference_file: str = ""
    namespace: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.name or not self.type_name:
            raise SnapshotValidationError("Node id, name, and type_name are required")
        object.__setattr__(self, "dag_paths", tuple(self.dag_paths))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True)
class SceneEdge:
    source_id: str
    target_id: str
    relation: str = "dg"
    source_plug: str = ""
    target_plug: str = ""

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id:
            raise SnapshotValidationError("Edge endpoints are required")
        if self.relation not in {"dg", "dag"}:
            raise SnapshotValidationError("Unsupported edge relation: %s" % self.relation)


@dataclass(frozen=True)
class SceneReference:
    reference_node: str
    resolved_path: str
    unresolved_path: str = ""
    canonical_path: str = ""
    copy_number: int = 0
    exists: bool | None = None
    namespace: str = ""
    parent_reference_node: str = ""
    loaded: bool = True
    preview_only: bool = False
    node_ids: Tuple[str, ...] = ()
    failed_edit_count: int = 0
    failed_edit_samples: Tuple[str, ...] = ()
    failed_edit_scan_complete: bool = True

    def __post_init__(self) -> None:
        if not self.reference_node or not self.resolved_path:
            raise SnapshotValidationError("Reference node and resolved path are required")
        if self.failed_edit_count < 0:
            raise SnapshotValidationError("Reference failed edit count cannot be negative")
        if self.copy_number < 0:
            raise SnapshotValidationError("Reference copy number cannot be negative")
        if self.exists is not None and not isinstance(self.exists, bool):
            raise SnapshotValidationError("Reference exists must be boolean or null")
        object.__setattr__(self, "node_ids", tuple(self.node_ids))
        object.__setattr__(self, "failed_edit_samples", tuple(self.failed_edit_samples))
        if len(self.failed_edit_samples) > self.failed_edit_count:
            raise SnapshotValidationError("Reference failed edit samples exceed their count")


@dataclass(frozen=True)
class UnknownPlugin:
    """A missing plug-in requirement preserved by the Maya scene file."""

    name: str
    version: str = ""
    node_types: Tuple[str, ...] = ()
    data_types: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise SnapshotValidationError("Unknown plug-in name is required")
        object.__setattr__(self, "node_types", tuple(self.node_types))
        object.__setattr__(self, "data_types", tuple(self.data_types))
        if len(self.node_types) != len(set(self.node_types)):
            raise SnapshotValidationError("Unknown plug-in node types contain duplicates")
        if len(self.data_types) != len(set(self.data_types)):
            raise SnapshotValidationError("Unknown plug-in data types contain duplicates")


@dataclass(frozen=True)
class SceneSettings:
    """Host settings that can silently change animation and publish semantics."""

    time_unit: str = ""
    frames_per_second: float = 0.0
    linear_unit: str = ""
    angular_unit: str = ""
    up_axis: str = ""
    color_management_enabled: bool | None = None
    rendering_space: str = ""
    view_transform: str = ""
    color_config_path: str = ""

    def __post_init__(self) -> None:
        if self.frames_per_second < 0:
            raise SnapshotValidationError("Scene frames_per_second cannot be negative")
        if self.up_axis and self.up_axis not in {"y", "z"}:
            raise SnapshotValidationError("Scene up_axis must be y or z")
        if self.color_management_enabled is not None and not isinstance(
            self.color_management_enabled, bool
        ):
            raise SnapshotValidationError("Scene color_management_enabled must be boolean or null")


@dataclass(frozen=True)
class ExternalDependency:
    """One Maya-managed external file plug, resolved without touching its contents."""

    id: str
    node_id: str
    node_name: str
    node_type: str
    attribute: str
    kind: str
    raw_path: str
    resolved_path: str
    exists: bool | None = None
    path_kind: str = "unknown"
    inside_workspace: bool | None = None
    sequence_pattern: str = ""
    sequence_kind: str = ""
    sequence_member_count: int = 0
    sequence_expected_count: int | None = None
    sequence_missing_count: int | None = None
    sequence_missing_samples: Tuple[str, ...] = ()
    sequence_scan_complete: bool = False
    sequence_scan_reason: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.node_id or not self.attribute or not self.kind:
            raise SnapshotValidationError(
                "External dependency id, node_id, attribute, and kind are required"
            )
        if self.exists is not None and not isinstance(self.exists, bool):
            raise SnapshotValidationError("External dependency exists must be boolean or null")
        if self.inside_workspace is not None and not isinstance(self.inside_workspace, bool):
            raise SnapshotValidationError(
                "External dependency inside_workspace must be boolean or null"
            )
        if self.sequence_kind not in {"", "frame", "udim", "uvtile"}:
            raise SnapshotValidationError("Unsupported external sequence kind")
        if not isinstance(self.sequence_scan_complete, bool):
            raise SnapshotValidationError("Sequence scan complete must be boolean")
        if self.sequence_member_count < 0:
            raise SnapshotValidationError("Sequence member count cannot be negative")
        if self.sequence_expected_count is not None and self.sequence_expected_count < 0:
            raise SnapshotValidationError("Sequence expected count cannot be negative")
        if self.sequence_missing_count is not None and self.sequence_missing_count < 0:
            raise SnapshotValidationError("Sequence missing count cannot be negative")
        if (
            self.sequence_expected_count is not None
            and self.sequence_missing_count is not None
            and self.sequence_missing_count > self.sequence_expected_count
        ):
            raise SnapshotValidationError("Sequence missing count exceeds expected count")
        object.__setattr__(self, "sequence_missing_samples", tuple(self.sequence_missing_samples))
        if (
            self.sequence_missing_count is not None
            and len(self.sequence_missing_samples) > self.sequence_missing_count
        ):
            raise SnapshotValidationError("Sequence missing samples exceed their count")


@dataclass(frozen=True)
class SceneLifecycle:
    """In-memory file/session state that is distinct from serialized scene content."""

    modified: bool | None = None
    file_type: str = ""
    workspace_root: str = ""
    current_time: float = 0.0
    playback_min: float = 0.0
    playback_max: float = 0.0
    animation_start: float = 0.0
    animation_end: float = 0.0

    def __post_init__(self) -> None:
        if self.modified is not None and not isinstance(self.modified, bool):
            raise SnapshotValidationError("Scene lifecycle modified must be boolean or null")


@dataclass(frozen=True)
class SceneSnapshot:
    nodes: Tuple[SceneNode, ...]
    edges: Tuple[SceneEdge, ...]
    references: Tuple[SceneReference, ...] = ()
    unknown_plugins: Tuple[UnknownPlugin, ...] = ()
    external_dependencies: Tuple[ExternalDependency, ...] = ()
    snapshot_id: str = field(default_factory=lambda: str(uuid4()))
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_scene: str = ""
    maya_version: str = ""
    scene_settings: SceneSettings = field(default_factory=SceneSettings)
    scene_lifecycle: SceneLifecycle = field(default_factory=SceneLifecycle)
    schema_version: int = SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "unknown_plugins", tuple(self.unknown_plugins))
        object.__setattr__(self, "external_dependencies", tuple(self.external_dependencies))
        if isinstance(self.scene_settings, Mapping):
            object.__setattr__(self, "scene_settings", SceneSettings(**self.scene_settings))
        if isinstance(self.scene_lifecycle, Mapping):
            object.__setattr__(self, "scene_lifecycle", SceneLifecycle(**self.scene_lifecycle))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        self.validate()

    @property
    def node_map(self) -> Dict[str, SceneNode]:
        return {node.id: node for node in self.nodes}

    def validate(self) -> None:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise SnapshotValidationError("Snapshot contains duplicate node ids")
        known = set(ids)
        for edge in self.edges:
            if edge.source_id not in known or edge.target_id not in known:
                raise SnapshotValidationError(
                    "Dangling edge %s -> %s" % (edge.source_id, edge.target_id)
                )
        reference_nodes = [reference.reference_node for reference in self.references]
        if len(reference_nodes) != len(set(reference_nodes)):
            raise SnapshotValidationError("Snapshot contains duplicate reference nodes")
        for reference in self.references:
            missing = set(reference.node_ids).difference(known)
            if missing:
                raise SnapshotValidationError(
                    "Reference %s contains dangling node %s"
                    % (reference.reference_node, sorted(missing)[0])
                )
        unknown_plugin_names = [plugin.name for plugin in self.unknown_plugins]
        if len(unknown_plugin_names) != len(set(unknown_plugin_names)):
            raise SnapshotValidationError("Snapshot contains duplicate unknown plug-ins")
        for dependency in self.external_dependencies:
            if dependency.node_id not in known:
                raise SnapshotValidationError(
                    "External dependency %s references missing node %s"
                    % (dependency.id, dependency.node_id)
                )
        dependency_ids = [dependency.id for dependency in self.external_dependencies]
        if len(dependency_ids) != len(set(dependency_ids)):
            raise SnapshotValidationError("Snapshot contains duplicate external dependency ids")

    def summary(self) -> Dict[str, int]:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "dag_edges": sum(edge.relation == "dag" for edge in self.edges),
            "dg_edges": sum(edge.relation == "dg" for edge in self.edges),
            "referenced_nodes": sum(node.referenced for node in self.nodes),
            "references": len(self.references),
            "reference_source_files": len(
                {
                    (reference.canonical_path or reference.resolved_path)
                    .replace("\\", "/")
                    .casefold()
                    for reference in self.references
                }
            ),
            "missing_reference_files": sum(
                reference.exists is False for reference in self.references
            ),
            "reference_copy_instances": sum(
                reference.copy_number > 0 for reference in self.references
            ),
            "unloaded_references": sum(not reference.loaded for reference in self.references),
            "failed_reference_edits": sum(reference.failed_edit_count for reference in self.references),
            "unknown_plugins": len(self.unknown_plugins),
            "unknown_plugin_node_types": sum(
                len(plugin.node_types) for plugin in self.unknown_plugins
            ),
            "external_dependencies": len(self.external_dependencies),
            "missing_external_dependencies": sum(
                dependency.exists is False for dependency in self.external_dependencies
            ),
            "external_sequence_dependencies": sum(
                bool(dependency.sequence_pattern) for dependency in self.external_dependencies
            ),
            "incomplete_external_sequences": sum(
                dependency.sequence_scan_complete
                and bool(dependency.sequence_missing_count)
                for dependency in self.external_dependencies
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "captured_at": self.captured_at,
            "source_scene": self.source_scene,
            "maya_version": self.maya_version,
            "scene_settings": asdict(self.scene_settings),
            "scene_lifecycle": asdict(self.scene_lifecycle),
            "metadata": dict(self.metadata),
            "references": [asdict(reference) for reference in self.references],
            "unknown_plugins": [asdict(plugin) for plugin in self.unknown_plugins],
            "external_dependencies": [
                asdict(dependency) for dependency in self.external_dependencies
            ],
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SceneSnapshot":
        try:
            payload = SNAPSHOT_MIGRATIONS.migrate(payload)
        except SchemaMigrationError as exc:
            raise SnapshotValidationError(str(exc)) from exc
        version = int(payload["schema_version"])
        return cls(
            nodes=tuple(SceneNode(**node) for node in payload.get("nodes", ())),
            edges=tuple(SceneEdge(**edge) for edge in payload.get("edges", ())),
            references=tuple(
                SceneReference(**reference) for reference in payload.get("references", ())
            ),
            unknown_plugins=tuple(
                UnknownPlugin(**plugin) for plugin in payload.get("unknown_plugins", ())
            ),
            external_dependencies=tuple(
                ExternalDependency(**dependency)
                for dependency in payload.get("external_dependencies", ())
            ),
            snapshot_id=str(payload.get("snapshot_id", "")),
            captured_at=str(payload.get("captured_at", "")),
            source_scene=str(payload.get("source_scene", "")),
            maya_version=str(payload.get("maya_version", "")),
            scene_settings=SceneSettings(**payload.get("scene_settings", {})),
            scene_lifecycle=SceneLifecycle(**payload.get("scene_lifecycle", {})),
            schema_version=SCHEMA_VERSION,
            metadata=payload.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, value: str) -> "SceneSnapshot":
        return cls.from_dict(json.loads(value))

    @classmethod
    def build(
        cls,
        nodes: Iterable[SceneNode],
        edges: Iterable[SceneEdge],
        references: Iterable[SceneReference] = (),
        external_dependencies: Iterable[ExternalDependency] = (),
        unknown_plugins: Iterable[UnknownPlugin] = (),
        **kwargs: Any,
    ) -> "SceneSnapshot":
        return cls(
            nodes=tuple(nodes),
            edges=tuple(edges),
            references=tuple(references),
            unknown_plugins=tuple(unknown_plugins),
            external_dependencies=tuple(external_dependencies),
            **kwargs,
        )
