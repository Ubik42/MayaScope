"""Orchestrate ddmin probes and persist a shareable Repro Capsule manifest."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from typing import Callable, Mapping, Optional, Tuple

from ..analysis.ddmin import DeltaDebugResult, DeltaDebugStep, minimize_failing_set
from ..model import BisectPlan, ProbeAttempt, ReproCapsuleManifest
from .isolated import IsolatedMayaProbe, sha256_file


@dataclass(frozen=True)
class BisectSessionResult:
    delta_debug: DeltaDebugResult
    manifest: ReproCapsuleManifest
    manifest_path: Path
    manifest_sha256: str


@dataclass(frozen=True)
class BisectJournal:
    plan: BisectPlan
    attempts: Tuple[ProbeAttempt, ...]
    status: str

    def __post_init__(self):
        object.__setattr__(self, "attempts", tuple(self.attempts))
        if self.status not in {"active", "paused", "finalized"}:
            raise ValueError("Invalid Bisect Journal status")


def load_repro_capsule(path: os.PathLike | str) -> ReproCapsuleManifest:
    candidate = Path(path).expanduser().resolve()
    try:
        envelope = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Unreadable Repro Capsule: %s" % exc) from exc
    expected = str(envelope.pop("checksum", ""))
    actual = hashlib.sha256(_canonical_json(envelope)).hexdigest()
    if not expected or expected != actual:
        raise ValueError("Repro Capsule checksum mismatch")
    if envelope.get("format") != "mayascope.repro-capsule":
        raise ValueError("Not a MayaScope Repro Capsule")
    if int(envelope.get("store_schema", 0)) != 1:
        raise ValueError("Unsupported Repro Capsule store schema")
    return ReproCapsuleManifest.from_dict(envelope["manifest"])


def load_bisect_journal(path: os.PathLike | str) -> BisectJournal:
    envelope = _load_checked_envelope(path, "mayascope.bisect-journal")
    return BisectJournal(
        plan=BisectPlan.from_dict(envelope["plan"]),
        attempts=tuple(
            ProbeAttempt(**attempt) for attempt in envelope.get("attempts", ())
        ),
        status=str(envelope.get("status", "")),
    )


def _canonical_json(payload) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _load_checked_envelope(path: os.PathLike | str, expected_format: str):
    candidate = Path(path).expanduser().resolve()
    try:
        envelope = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Unreadable %s: %s" % (expected_format, exc)) from exc
    expected = str(envelope.pop("checksum", ""))
    actual = hashlib.sha256(_canonical_json(envelope)).hexdigest()
    if not expected or expected != actual:
        raise ValueError("%s checksum mismatch" % expected_format)
    if envelope.get("format") != expected_format:
        raise ValueError("Unexpected evidence format")
    if int(envelope.get("store_schema", 0)) != 1:
        raise ValueError("Unsupported evidence store schema")
    return envelope


def _write_checked_envelope(path: Path, envelope: Mapping) -> str:
    unsigned = dict(envelope)
    checksum = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    payload = dict(unsigned)
    payload["checksum"] = checksum
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "wb") as stream:
        stream.write(_canonical_json(payload))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))
    return checksum


class BisectSession:
    def __init__(
        self,
        plan: BisectPlan,
        root: os.PathLike | str | None = None,
        probe=None,
        prior_attempts: Tuple[ProbeAttempt, ...] = (),
    ):
        self.plan = plan
        self.probe = probe or IsolatedMayaProbe(plan, root=root)
        self.prior_attempts = tuple(prior_attempts)
        known_ids = {candidate.id for candidate in plan.candidates}
        outcomes = {}
        for expected_index, attempt in enumerate(self.prior_attempts):
            if attempt.attempt_index != expected_index:
                raise ValueError("Bisect Journal attempt indices are not contiguous")
            if not set(attempt.candidate_ids).issubset(known_ids):
                raise ValueError("Bisect Journal contains an unknown candidate")
            key = frozenset(attempt.candidate_ids)
            if key in outcomes and outcomes[key] != attempt.outcome:
                raise ValueError("Bisect Journal contains conflicting outcomes")
            outcomes[key] = attempt.outcome

    @classmethod
    def resume(
        cls,
        journal_path: os.PathLike | str,
        probe=None,
        *,
        validate_source: bool = True,
    ) -> "BisectSession":
        path = Path(journal_path).expanduser().resolve()
        journal = load_bisect_journal(path)
        if validate_source:
            source = Path(journal.plan.source_scene).expanduser().resolve()
            if not source.is_file() or sha256_file(source) != journal.plan.source_sha256:
                raise ValueError(
                    "Bisect source is missing or changed since the Journal was written"
                )
        return cls(
            journal.plan,
            root=path.parent,
            probe=probe,
            prior_attempts=journal.attempts,
        )

    def _write_journal(self, attempts, status: str) -> Path:
        root = Path(self.probe.root)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "bisect-journal.json"
        _write_checked_envelope(
            path,
            {
                "format": "mayascope.bisect-journal",
                "store_schema": 1,
                "plan": self.plan.to_dict(),
                "attempts": [
                    {
                        "attempt_index": item.attempt_index,
                        "candidate_ids": item.candidate_ids,
                        "outcome": item.outcome,
                        "stage": item.stage,
                        "duration_seconds": item.duration_seconds,
                        "exit_code": item.exit_code,
                        "timed_out": item.timed_out,
                        "work_copy": item.work_copy,
                        "stdout_tail": item.stdout_tail,
                        "stderr_tail": item.stderr_tail,
                        "crash_artifacts": item.crash_artifacts,
                        "environment": item.environment,
                        "started_at": item.started_at,
                    }
                    for item in attempts
                ],
                "status": status,
            },
        )
        return path

    def run(
        self,
        *,
        max_probes: int = 256,
        cancelled: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[DeltaDebugStep, ProbeAttempt], None]] = None,
    ) -> BisectSessionResult:
        attempts = list(self.prior_attempts)
        latest_attempt = [None]
        known_outcomes = {
            frozenset(attempt.candidate_ids): attempt.outcome
            for attempt in self.prior_attempts
        }
        self._write_journal(attempts, "active")

        def oracle(candidate_ids: Tuple[str, ...]) -> str:
            attempt = self.probe.run(candidate_ids, len(attempts))
            attempts.append(attempt)
            self._write_journal(attempts, "active")
            latest_attempt[0] = attempt
            return attempt.outcome

        def on_step(step: DeltaDebugStep) -> None:
            if progress and not step.cached and latest_attempt[0] is not None:
                progress(step, latest_attempt[0])
            latest_attempt[0] = None

        result = minimize_failing_set(
            tuple(candidate.id for candidate in self.plan.candidates),
            oracle,
            max_probes=max_probes,
            cancelled=cancelled,
            progress=on_step,
            known_outcomes=known_outcomes,
        )
        maya_environments = [item.environment for item in attempts if item.environment]
        manifest = ReproCapsuleManifest(
            plan=self.plan,
            attempts=tuple(attempts),
            minimal_candidate_ids=result.minimal_candidate_ids,
            complete=result.complete,
            reason=result.reason,
            environment={
                "platform": platform.platform(),
                "python": sys.version,
                "maya_executable": self.plan.maya_executable,
                "probe_count": len(attempts),
                "new_probe_count": result.probe_count,
                "cache_hits": result.cache_hits,
                "maya": maya_environments[-1] if maya_environments else {},
            },
        )
        root = Path(self.probe.root)
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "repro-capsule.json"
        envelope = {
            "format": "mayascope.repro-capsule",
            "store_schema": 1,
            "manifest": manifest.to_dict(),
        }
        checksum = _write_checked_envelope(manifest_path, envelope)
        self._write_journal(
            attempts, "finalized" if result.complete else "paused"
        )
        return BisectSessionResult(result, manifest, manifest_path, checksum)
