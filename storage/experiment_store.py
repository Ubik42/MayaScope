"""Atomic, checksummed archive for Counterfactual Profiler evidence."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Tuple

from ..analysis.counterfactual import CounterfactualReport


STORE_FORMAT = "mayascope.counterfactual-experiment"
STORE_SCHEMA = 1


class ExperimentStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExperimentRecord:
    path: Path
    report: CounterfactualReport
    checksum: str


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _safe_fragment(value: str, fallback: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return fragment[:48] or fallback


class ExperimentStore:
    def __init__(self, root: os.PathLike | str | None = None):
        if root is None:
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            root = base / "MayaScope" / "experiments"
        self.root = Path(root).expanduser().resolve()

    def save(self, report: CounterfactualReport) -> ExperimentRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = report.to_dict()
        checksum = hashlib.sha256(_canonical_json(payload)).hexdigest()
        envelope = {
            "format": STORE_FORMAT,
            "store_schema": STORE_SCHEMA,
            "checksum": checksum,
            "report": payload,
        }
        stamp = _safe_fragment(report.captured_at.replace(":", "-"), "experiment")
        target = _safe_fragment(report.target_name, "target")
        identity = _safe_fragment(report.experiment_id, "experiment")
        destination = self.root / (
            "%s-%s-%s.msexperiment.json.gz" % (stamp, target, identity)
        )
        if destination.exists():
            destination = self.root / (
                "%s-%s-%s-%s.msexperiment.json.gz"
                % (stamp, target, identity, hashlib.sha1(os.urandom(16)).hexdigest()[:6])
            )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".mayascope-experiment-", suffix=".tmp", dir=str(self.root)
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
            raise ExperimentStoreError(
                "Could not atomically save counterfactual evidence: %s" % exc
            ) from exc
        return ExperimentRecord(destination, report, checksum)

    def load(self, path: os.PathLike | str) -> ExperimentRecord:
        candidate = self._owned_path(path)
        try:
            with gzip.open(str(candidate), "rb") as stream:
                envelope = json.loads(stream.read().decode("utf-8"))
        except Exception as exc:
            raise ExperimentStoreError(
                "Unreadable experiment archive %s: %s" % (candidate.name, exc)
            ) from exc
        if envelope.get("format") != STORE_FORMAT:
            raise ExperimentStoreError("Not a MayaScope experiment archive: %s" % candidate.name)
        if int(envelope.get("store_schema", 0)) != STORE_SCHEMA:
            raise ExperimentStoreError("Unsupported experiment store schema")
        payload = envelope.get("report")
        expected = str(envelope.get("checksum", ""))
        actual = hashlib.sha256(_canonical_json(payload)).hexdigest()
        if not expected or expected != actual:
            raise ExperimentStoreError("Experiment checksum mismatch: %s" % candidate.name)
        try:
            report = CounterfactualReport.from_dict(payload)
        except Exception as exc:
            raise ExperimentStoreError("Invalid experiment payload: %s" % exc) from exc
        return ExperimentRecord(candidate, report, actual)

    def list_records(self) -> Tuple[ExperimentRecord, ...]:
        if not self.root.exists():
            return ()
        records = [self.load(path) for path in self.root.glob("*.msexperiment.json.gz")]
        records.sort(key=lambda record: record.report.captured_at, reverse=True)
        return tuple(records)

    def _owned_path(self, path: os.PathLike | str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        candidate = candidate.expanduser().resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Experiment path escapes store root") from exc
        return candidate
