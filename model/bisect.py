"""Versioned contracts for isolated Crash & Corruption Bisect investigations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, Mapping, Tuple
from uuid import uuid4


BISECT_SCHEMA_VERSION = 1
PROBE_OUTCOMES = frozenset({"pass", "fail", "unresolved"})
PROBE_STAGES = frozenset({"prepare", "open", "evaluate", "save", "reopen", "exit"})


def _freeze_jsonish(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _freeze_jsonish(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_jsonish(item) for item in value)
    return value


@dataclass(frozen=True)
class BisectCandidate:
    id: str
    label: str
    kind: str
    stable_node_ids: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.label or not self.kind:
            raise ValueError("Bisect candidate id, label, and kind are required")
        object.__setattr__(self, "stable_node_ids", tuple(self.stable_node_ids))
        object.__setattr__(self, "metadata", _freeze_jsonish(self.metadata))


@dataclass(frozen=True)
class BisectPlan:
    source_scene: str
    source_sha256: str
    candidates: Tuple[BisectCandidate, ...]
    maya_executable: str
    timeout_seconds: float = 120.0
    stages: Tuple[str, ...] = ("open", "evaluate", "save", "reopen")
    plan_id: str = field(default_factory=lambda: "bisect-%s" % uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = BISECT_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "stages", tuple(self.stages))
        object.__setattr__(self, "metadata", _freeze_jsonish(self.metadata))
        if not self.source_scene or not self.source_sha256 or not self.maya_executable:
            raise ValueError("Bisect source, checksum, and Maya executable are required")
        if self.timeout_seconds <= 0:
            raise ValueError("Bisect timeout must be positive")
        ids = tuple(candidate.id for candidate in self.candidates)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Bisect candidates must be non-empty and uniquely identified")
        invalid = set(self.stages).difference(PROBE_STAGES)
        if invalid:
            raise ValueError("Unsupported Bisect stage: %s" % sorted(invalid)[0])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BisectPlan":
        version = int(payload.get("schema_version", 0))
        if version != BISECT_SCHEMA_VERSION:
            raise ValueError("Unsupported BisectPlan schema: %s" % version)
        values = dict(payload)
        values["candidates"] = tuple(
            BisectCandidate(**candidate) for candidate in payload.get("candidates", ())
        )
        values["stages"] = tuple(payload.get("stages", ()))
        return cls(**values)

    @classmethod
    def from_json(cls, value: str) -> "BisectPlan":
        return cls.from_dict(json.loads(value))


@dataclass(frozen=True)
class ProbeAttempt:
    attempt_index: int
    candidate_ids: Tuple[str, ...]
    outcome: str
    stage: str
    duration_seconds: float
    exit_code: int | None = None
    timed_out: bool = False
    work_copy: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""
    crash_artifacts: Tuple[str, ...] = ()
    environment: Mapping[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_ids", tuple(self.candidate_ids))
        object.__setattr__(self, "crash_artifacts", tuple(self.crash_artifacts))
        object.__setattr__(self, "environment", _freeze_jsonish(self.environment))
        if self.attempt_index < 0 or self.duration_seconds < 0:
            raise ValueError("Invalid ProbeAttempt timing or index")
        if self.outcome not in PROBE_OUTCOMES:
            raise ValueError("Invalid ProbeAttempt outcome")
        if self.stage not in PROBE_STAGES:
            raise ValueError("Invalid ProbeAttempt stage")


@dataclass(frozen=True)
class ReproCapsuleManifest:
    plan: BisectPlan
    attempts: Tuple[ProbeAttempt, ...]
    minimal_candidate_ids: Tuple[str, ...]
    complete: bool
    reason: str
    environment: Mapping[str, Any] = field(default_factory=dict)
    capsule_id: str = field(default_factory=lambda: "capsule-%s" % uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = BISECT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(self, "minimal_candidate_ids", tuple(self.minimal_candidate_ids))
        object.__setattr__(self, "environment", _freeze_jsonish(self.environment))
        known = {candidate.id for candidate in self.plan.candidates}
        if not set(self.minimal_candidate_ids).issubset(known):
            raise ValueError("Repro Capsule references an unknown candidate")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReproCapsuleManifest":
        version = int(payload.get("schema_version", 0))
        if version != BISECT_SCHEMA_VERSION:
            raise ValueError("Unsupported ReproCapsule schema: %s" % version)
        return cls(
            plan=BisectPlan.from_dict(payload["plan"]),
            attempts=tuple(ProbeAttempt(**attempt) for attempt in payload.get("attempts", ())),
            minimal_candidate_ids=tuple(payload.get("minimal_candidate_ids", ())),
            complete=bool(payload.get("complete", False)),
            reason=str(payload.get("reason", "")),
            environment=payload.get("environment", {}),
            capsule_id=str(payload.get("capsule_id", "")),
            created_at=str(payload.get("created_at", "")),
            schema_version=version,
        )

    @classmethod
    def from_json(cls, value: str) -> "ReproCapsuleManifest":
        return cls.from_dict(json.loads(value))
