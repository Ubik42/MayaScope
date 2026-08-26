"""Atomic and checksummed local SceneSnapshot archive."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Tuple

from ..model import SceneSnapshot


STORE_FORMAT = "mayascope.scene-snapshot"
STORE_SCHEMA = 1


class SnapshotStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotRecord:
    path: Path
    snapshot: SceneSnapshot
    label: str
    checksum: str


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _safe_fragment(value: str, fallback: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return fragment[:48] or fallback


class SnapshotStore:
    def __init__(self, root: os.PathLike | str | None = None):
        if root is None:
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            root = base / "MayaScope" / "snapshots"
        self.root = Path(root).expanduser().resolve()

    def save(self, snapshot: SceneSnapshot, label: str = "") -> SnapshotRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        snapshot_payload = snapshot.to_dict()
        checksum = hashlib.sha256(_canonical_json(snapshot_payload)).hexdigest()
        envelope = {
            "format": STORE_FORMAT,
            "store_schema": STORE_SCHEMA,
            "label": str(label),
            "checksum": checksum,
            "snapshot": snapshot_payload,
        }
        stamp = _safe_fragment(snapshot.captured_at.replace(":", "-"), "capture")
        identity = _safe_fragment(snapshot.snapshot_id, "snapshot")
        label_part = "-%s" % _safe_fragment(label, "") if label else ""
        destination = self.root / ("%s-%s%s.mscope.json.gz" % (stamp, identity, label_part))
        if destination.exists():
            destination = self.root / (
                "%s-%s%s-%s.mscope.json.gz"
                % (stamp, identity, label_part, hashlib.sha1(os.urandom(16)).hexdigest()[:6])
            )

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".mayascope-", suffix=".tmp", dir=str(self.root)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as raw:
                with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                    compressed.write(_canonical_json(envelope))
                raw.flush()
                os.fsync(raw.fileno())
            os.replace(str(temporary), str(destination))
        except Exception as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise SnapshotStoreError("Could not atomically save snapshot: %s" % exc) from exc
        return SnapshotRecord(destination, snapshot, str(label), checksum)

    def load(self, path: os.PathLike | str) -> SnapshotRecord:
        candidate = self._owned_path(path)
        try:
            with gzip.open(str(candidate), "rb") as stream:
                envelope = json.loads(stream.read().decode("utf-8"))
        except Exception as exc:
            raise SnapshotStoreError("Unreadable snapshot archive %s: %s" % (candidate.name, exc)) from exc
        if envelope.get("format") != STORE_FORMAT:
            raise SnapshotStoreError("Not a MayaScope snapshot archive: %s" % candidate.name)
        if int(envelope.get("store_schema", 0)) != STORE_SCHEMA:
            raise SnapshotStoreError("Unsupported snapshot store schema")
        snapshot_payload = envelope.get("snapshot")
        expected = str(envelope.get("checksum", ""))
        actual = hashlib.sha256(_canonical_json(snapshot_payload)).hexdigest()
        if not expected or actual != expected:
            raise SnapshotStoreError("Snapshot checksum mismatch: %s" % candidate.name)
        try:
            snapshot = SceneSnapshot.from_dict(snapshot_payload)
        except Exception as exc:
            raise SnapshotStoreError("Invalid snapshot payload: %s" % exc) from exc
        return SnapshotRecord(candidate, snapshot, str(envelope.get("label", "")), actual)

    def list_records(self) -> Tuple[SnapshotRecord, ...]:
        if not self.root.exists():
            return ()
        records = [self.load(path) for path in self.root.glob("*.mscope.json.gz")]
        records.sort(key=lambda record: record.snapshot.captured_at, reverse=True)
        return tuple(records)

    def _owned_path(self, path: os.PathLike | str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        candidate = candidate.expanduser().resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Snapshot path escapes store root") from exc
        return candidate
