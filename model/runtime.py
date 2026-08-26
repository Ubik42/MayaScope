"""Immutable execution-surface inventory independent of Maya and Qt."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Tuple
from uuid import uuid4


RUNTIME_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RuntimeScriptJob:
    job_id: int
    trigger_kind: str
    trigger: str
    protected: bool
    permanent: bool
    kill_with_scene: bool
    descriptor_sha256: str
    descriptor_preview: str


@dataclass(frozen=True)
class RuntimeExpression:
    node_id: str
    node_name: str
    object_name: str
    always_evaluate: bool
    unit_conversion: str
    source_sha256: str
    source_length: int
    source_preview: str
    referenced: bool = False


@dataclass(frozen=True)
class RuntimePlugin:
    name: str
    path: str
    vendor: str
    version: str
    api_version: str
    autoload: bool
    unload_ok: bool
    node_types: Tuple[str, ...] = ()
    commands: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "node_types", tuple(self.node_types))
        object.__setattr__(self, "commands", tuple(self.commands))


@dataclass(frozen=True)
class RuntimeNodeCallbacks:
    node_id: str
    node_name: str
    callback_count: int

    def __post_init__(self):
        if self.callback_count < 1:
            raise ValueError("Runtime callback records require a positive count")


@dataclass(frozen=True)
class RuntimeSnapshot:
    source_snapshot_id: str
    script_jobs: Tuple[RuntimeScriptJob, ...]
    expressions: Tuple[RuntimeExpression, ...]
    plugins: Tuple[RuntimePlugin, ...]
    node_callbacks: Tuple[RuntimeNodeCallbacks, ...]
    script_jobs_available: bool
    batch_mode: bool
    maya_version: str
    runtime_id: str = field(default_factory=lambda: str(uuid4()))
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    callback_visibility: str = "仅能看到节点范围的不透明 ID；无法全局枚举所有者或函数"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = RUNTIME_SCHEMA_VERSION

    def __post_init__(self):
        object.__setattr__(self, "script_jobs", tuple(self.script_jobs))
        object.__setattr__(self, "expressions", tuple(self.expressions))
        object.__setattr__(self, "plugins", tuple(self.plugins))
        object.__setattr__(self, "node_callbacks", tuple(self.node_callbacks))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.schema_version != RUNTIME_SCHEMA_VERSION:
            raise ValueError("Unsupported RuntimeSnapshot schema")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime_id": self.runtime_id,
            "captured_at": self.captured_at,
            "source_snapshot_id": self.source_snapshot_id,
            "script_jobs_available": self.script_jobs_available,
            "batch_mode": self.batch_mode,
            "maya_version": self.maya_version,
            "callback_visibility": self.callback_visibility,
            "metadata": dict(self.metadata),
            "script_jobs": [asdict(item) for item in self.script_jobs],
            "expressions": [asdict(item) for item in self.expressions],
            "plugins": [asdict(item) for item in self.plugins],
            "node_callbacks": [asdict(item) for item in self.node_callbacks],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]):
        version = int(payload.get("schema_version", 0))
        if version != RUNTIME_SCHEMA_VERSION:
            raise ValueError("Unsupported RuntimeSnapshot schema: %s" % version)
        return cls(
            runtime_id=str(payload.get("runtime_id", "")),
            captured_at=str(payload.get("captured_at", "")),
            source_snapshot_id=str(payload.get("source_snapshot_id", "")),
            script_jobs=tuple(RuntimeScriptJob(**item) for item in payload.get("script_jobs", ())),
            expressions=tuple(RuntimeExpression(**item) for item in payload.get("expressions", ())),
            plugins=tuple(RuntimePlugin(**item) for item in payload.get("plugins", ())),
            node_callbacks=tuple(RuntimeNodeCallbacks(**item) for item in payload.get("node_callbacks", ())),
            script_jobs_available=bool(payload.get("script_jobs_available", False)),
            batch_mode=bool(payload.get("batch_mode", False)),
            maya_version=str(payload.get("maya_version", "")),
            callback_visibility=str(payload.get("callback_visibility", "")),
            metadata=payload.get("metadata", {}),
            schema_version=version,
        )
