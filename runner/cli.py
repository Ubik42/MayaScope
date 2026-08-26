"""Machine-readable MayaScope Crash Bisect entry point for CI and render farms."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from ..model import BisectPlan
from ..runtime_log import log_event
from .planning import build_pre_open_ascii_bisect_plan
from .session import BisectSession, load_bisect_journal, load_repro_capsule


def _emit(event: str, **payload) -> None:
    print(
        json.dumps(
            {"event": event, **payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


def _default_mayapy() -> Path:
    configured = os.environ.get("MAYASCOPE_MAYAPY")
    candidates = (
        Path(configured) if configured else None,
        Path(r"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe"),
    )
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        "Maya 2025 mayapy.exe not found; pass --mayapy or set MAYASCOPE_MAYAPY"
    )


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def _plan(args) -> BisectPlan:
    source = Path(args.scene).expanduser().resolve()
    if source.suffix.lower() != ".ma":
        raise ValueError(
            "Batch planning currently requires .ma; .mb needs a captured SceneSnapshot in Maya"
        )
    mayapy = Path(args.mayapy).expanduser().resolve() if args.mayapy else _default_mayapy()
    return build_pre_open_ascii_bisect_plan(
        str(source), str(mayapy), timeout_seconds=args.timeout
    )


def _progress(step, attempt) -> None:
    _emit(
        "probe",
        attempt=attempt.attempt_index,
        outcome=attempt.outcome,
        stage=attempt.stage,
        duration_seconds=round(attempt.duration_seconds, 6),
        candidate_count=len(step.candidate_ids),
        purpose=step.purpose,
        timed_out=attempt.timed_out,
    )


def _result_payload(result):
    return {
        "complete": result.delta_debug.complete,
        "reason": result.delta_debug.reason,
        "minimal_candidate_ids": result.delta_debug.minimal_candidate_ids,
        "total_probe_count": len(result.manifest.attempts),
        "new_probe_count": result.delta_debug.probe_count,
        "cache_hits": result.delta_debug.cache_hits,
        "capsule": str(result.manifest_path),
        "capsule_sha256": result.manifest_sha256,
    }


def _run(args) -> int:
    plan = _plan(args)
    log_event(
        "runner.plan",
        context={"plan_id": plan.plan_id, "candidate_count": len(plan.candidates)},
    )
    root = Path(args.root).expanduser().resolve() if args.root else None
    _emit(
        "plan",
        plan_id=plan.plan_id,
        source=plan.source_scene,
        source_sha256=plan.source_sha256,
        candidate_count=len(plan.candidates),
        isolation_mode=plan.metadata.get("isolation_mode"),
    )
    if args.plan_output:
        target = Path(args.plan_output).expanduser().resolve()
        _atomic_text(target, plan.to_json() + "\n")
        _emit("plan-written", path=str(target))
    if args.plan_only:
        return 0
    result = BisectSession(plan, root=root).run(
        max_probes=args.max_probes,
        progress=_progress,
    )
    _emit("result", **_result_payload(result))
    log_event(
        "runner.finished",
        context={
            "plan_id": plan.plan_id,
            "complete": result.delta_debug.complete,
            "attempt_count": len(result.manifest.attempts),
            "capsule_sha256": result.manifest_sha256,
        },
    )
    return 0 if result.delta_debug.complete else 2


def _resume(args) -> int:
    journal_path = Path(args.journal).expanduser().resolve()
    journal = load_bisect_journal(journal_path)
    _emit(
        "resume",
        plan_id=journal.plan.plan_id,
        verified_probe_count=len(journal.attempts),
        journal_status=journal.status,
    )
    result = BisectSession.resume(journal_path).run(
        max_probes=args.max_probes,
        progress=_progress,
    )
    _emit("result", **_result_payload(result))
    return 0 if result.delta_debug.complete else 2


def _verify(args) -> int:
    manifest = load_repro_capsule(args.capsule)
    _emit(
        "verified",
        capsule_id=manifest.capsule_id,
        plan_id=manifest.plan.plan_id,
        complete=manifest.complete,
        attempt_count=len(manifest.attempts),
        minimal_candidate_ids=manifest.minimal_candidate_ids,
        maya=manifest.environment.get("maya", {}),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mayascope-bisect")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="plan and execute a pre-open .ma bisect")
    run.add_argument("scene")
    run.add_argument("--mayapy")
    run.add_argument("--root")
    run.add_argument("--timeout", type=float, default=120.0)
    run.add_argument("--max-probes", type=int, default=256)
    run.add_argument("--plan-output")
    run.add_argument("--plan-only", action="store_true")
    run.set_defaults(handler=_run)

    resume = commands.add_parser("resume", help="continue a checksummed Bisect Journal")
    resume.add_argument("journal")
    resume.add_argument("--max-probes", type=int, default=256)
    resume.set_defaults(handler=_resume)

    verify = commands.add_parser("verify", help="verify and summarize a Repro Capsule")
    verify.add_argument("capsule")
    verify.set_defaults(handler=_verify)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:
        _emit("error", error_type=type(exc).__name__, message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
