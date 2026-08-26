"""Host-independent Maya Profiler capture contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, Iterable, Mapping, Tuple
from uuid import uuid4


PROFILER_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProfilerCategory:
    index: int
    name: str
    description: str = ""


@dataclass(frozen=True)
class ProfilerEvent:
    index: int
    start_us: int
    duration_us: int
    thread_duration_raw: int
    thread_id: int
    cpu_id: int
    category_index: int
    category_name: str
    color_index: int
    name: str
    extra: str = ""
    description: str = ""
    node_id: str = ""

    @property
    def end_us(self) -> int:
        return self.start_us + self.duration_us


@dataclass(frozen=True)
class ProfilerCapture:
    events: Tuple[ProfilerEvent, ...]
    categories: Tuple[ProfilerCategory, ...]
    capture_id: str = field(default_factory=lambda: str(uuid4()))
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_snapshot_id: str = ""
    source_scene: str = ""
    maya_version: str = ""
    schema_version: int = PROFILER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "categories", tuple(self.categories))
        object.__setattr__(self, "metadata", dict(self.metadata))
        indexes = [event.index for event in self.events]
        if len(indexes) != len(set(indexes)):
            raise ValueError("Profiler capture contains duplicate event indexes")
        if any(event.start_us < 0 or event.duration_us < 0 for event in self.events):
            raise ValueError("Profiler event times must be non-negative")

    @property
    def duration_us(self) -> int:
        return max((event.end_us for event in self.events), default=0)

    @property
    def mapped_event_count(self) -> int:
        return sum(bool(event.node_id) for event in self.events)

    def events_in_range(self, start_us: int, end_us: int) -> Tuple[ProfilerEvent, ...]:
        if end_us < start_us:
            start_us, end_us = end_us, start_us
        return tuple(
            event
            for event in self.events
            if event.end_us >= start_us and event.start_us <= end_us
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "capture_id": self.capture_id,
            "captured_at": self.captured_at,
            "source_snapshot_id": self.source_snapshot_id,
            "source_scene": self.source_scene,
            "maya_version": self.maya_version,
            "metadata": dict(self.metadata),
            "categories": [asdict(category) for category in self.categories],
            "events": [asdict(event) for event in self.events],
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProfilerCapture":
        version = int(payload.get("schema_version", 0))
        if version != PROFILER_SCHEMA_VERSION:
            raise ValueError("Unsupported ProfilerCapture schema: %s" % version)
        return cls(
            events=tuple(ProfilerEvent(**event) for event in payload.get("events", ())),
            categories=tuple(
                ProfilerCategory(**category) for category in payload.get("categories", ())
            ),
            capture_id=str(payload.get("capture_id", "")),
            captured_at=str(payload.get("captured_at", "")),
            source_snapshot_id=str(payload.get("source_snapshot_id", "")),
            source_scene=str(payload.get("source_scene", "")),
            maya_version=str(payload.get("maya_version", "")),
            schema_version=version,
            metadata=payload.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, value: str) -> "ProfilerCapture":
        return cls.from_dict(json.loads(value))
