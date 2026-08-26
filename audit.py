"""Read-only Scene Clinic CI gate using one hidden Maya 2025 process."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .doctor import locate_mayapy
from .analysis.regression import compare_audit_reports
from .audit_schema import migrate_audit_payload


SEVERITIES = {"info": 10, "warning": 20, "error": 30, "critical": 40, "never": 10**9}


def _canonical_json(payload) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload) -> str:
    envelope = dict(payload)
    checksum = hashlib.sha256(_canonical_json(envelope)).hexdigest()
    envelope["report_sha256"] = checksum
    data = json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))
    return checksum


def verify_audit_report(path: Path):
    report_path = path.expanduser().resolve()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if payload.get("format") != "mayascope.clinic-audit":
        raise ValueError("Not a MayaScope Scene Clinic audit report")
    expected = payload.pop("report_sha256", None)
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Audit report has no valid report_sha256")
    actual = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if actual != expected:
        raise ValueError("Audit report checksum mismatch")
    payload = migrate_audit_payload(payload)
    payload["report_sha256"] = expected
    return payload


def run_audit(
    scene: Path,
    *,
    profile: str = "all",
    fail_on: str = "error",
    mayapy=None,
    config: Path | None = None,
    workspace: Path | None = None,
    timeout: float = 300.0,
    performance_samples: int = 0,
    performance_warmups: int = 2,
    process_started=None,
    process_finished=None,
):
    source = scene.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".ma", ".mb"}:
        raise ValueError("Scene Clinic audit requires an existing .ma or .mb scene")
    if fail_on not in SEVERITIES:
        raise ValueError("Unknown severity threshold: %s" % fail_on)
    if performance_samples not in (0,) and not 3 <= performance_samples <= 101:
        raise ValueError("performance_samples must be zero or between 3 and 101")
    if not 0 <= performance_warmups <= 20:
        raise ValueError("performance_warmups must be between 0 and 20")
    executable = locate_mayapy(mayapy)
    workspace_path = None
    if workspace is not None:
        workspace_path = workspace.expanduser().resolve()
        if not workspace_path.is_dir():
            raise ValueError("Scene Clinic workspace must be an existing directory")
    package_parent = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="mayascope-audit-") as folder:
        root = Path(folder)
        request_path = root / "request.json"
        result_path = root / "result.json"
        request = {
            "scene": str(source),
            "source_sha256": _sha256(source),
            "profile": profile,
            "severity_threshold": SEVERITIES[fail_on],
            "performance_samples": performance_samples,
            "performance_warmups": performance_warmups,
            "result_path": str(result_path),
            "workspace": str(workspace_path) if workspace_path else "",
        }
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        environment = os.environ.copy()
        existing = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            value for value in (str(package_parent), existing) if value
        )
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["MAYA_APP_DIR"] = str(root / "maya_app")
        if config is not None:
            environment["MAYASCOPE_CLINIC_CONFIG"] = str(config.expanduser().resolve())
        command = (
            str(executable),
            "-m",
            "MayaScope.audit_worker",
            str(request_path),
        )
        process_event = None
        if process_started is None and process_finished is None:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(root),
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Scene Clinic audit timed out after %.1f seconds" % timeout) from exc
        else:
            from .process_guard import ChildJobGuard, get_process_identity

            process = subprocess.Popen(
                command,
                cwd=str(root),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                shell=False,
            )
            guard = ChildJobGuard(process)
            identity = get_process_identity(process.pid)
            process_event = {
                "pid": process.pid,
                "identity": identity.to_dict() if identity else None,
                "executable": str(executable),
                "request_path": str(request_path),
                "job_kill_on_close": bool(guard.assigned),
            }
            timed_out = False
            try:
                if process_started:
                    process_started(dict(process_event))
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate()
                raise RuntimeError(
                    "Scene Clinic audit timed out after %.1f seconds" % timeout
                ) from exc
            except BaseException:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
                raise
            finally:
                try:
                    if process_finished:
                        finished = dict(process_event)
                        finished.update({
                            "returncode": process.returncode,
                            "timed_out": timed_out,
                        })
                        process_finished(finished)
                finally:
                    guard.close()
            completed = subprocess.CompletedProcess(
                command, process.returncode, stdout=stdout, stderr=stderr
            )
        if not result_path.is_file():
            detail = (completed.stderr or completed.stdout or "no worker result")[-4000:]
            raise RuntimeError("Scene Clinic worker failed: %s" % detail)
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["worker_exit_code"] = completed.returncode
        expected_exit = 1 if not payload.get("ok", False) else 2 if payload.get("gate_failed", False) else 0
        if completed.returncode != expected_exit:
            raise RuntimeError(
                "Scene Clinic worker exit/report mismatch: exit %s, expected %s"
                % (completed.returncode, expected_exit)
            )
        return payload


def _summary(payload):
    regression = payload.get("regression") or {}
    performance = regression.get("performance") or {}
    return {
        "schema_version": payload.get("schema_version"),
        "ok": payload.get("ok", False),
        "gate_failed": payload.get("gate_failed", False),
        "worker_exit_code": payload.get("worker_exit_code"),
        "profile": payload.get("profile"),
        "issue_count": len(payload.get("issues", ())),
        "rule_failure_count": len(payload.get("rule_failures", ())),
        "source_sha256": payload.get("source_sha256"),
        "report_path": payload.get("report_path"),
        "report_sha256": payload.get("report_sha256"),
        "gate_mode": payload.get("gate_mode", "absolute"),
        "new_finding_count": len(regression.get("new_findings", ())),
        "escalated_finding_count": len(regression.get("escalated_findings", ())),
        "resolved_finding_count": len(regression.get("resolved_findings", ())),
        "performance_regressed": performance.get("regressed"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-audit")
    parser.add_argument("scene", type=Path, nargs="?")
    parser.add_argument("--profile", default="all")
    parser.add_argument("--fail-on", choices=tuple(SEVERITIES), default="error")
    parser.add_argument("--mayapy")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--performance-samples", type=int, default=0)
    parser.add_argument("--performance-warmups", type=int, default=2)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--gate-mode", choices=("absolute", "regression"), default="absolute")
    parser.add_argument("--max-slowdown", type=float, default=0.20)
    parser.add_argument("--min-slowdown-ms", type=float, default=2.0)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify_report:
            if args.scene is not None:
                parser.error("scene cannot be combined with --verify-report")
            payload = verify_audit_report(args.verify_report)
            print(json.dumps(_summary(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0
        if args.scene is None:
            parser.error("scene is required unless --verify-report is used")
        baseline = verify_audit_report(args.baseline_report) if args.baseline_report else None
        performance_samples = args.performance_samples
        if baseline and baseline.get("performance") and performance_samples == 0:
            performance_samples = int(baseline["performance"].get("sample_count", 0))
        payload = run_audit(
            args.scene,
            profile=args.profile,
            fail_on=args.fail_on,
            mayapy=args.mayapy,
            config=args.config,
            workspace=args.workspace,
            timeout=args.timeout,
            performance_samples=performance_samples,
            performance_warmups=args.performance_warmups,
        )
        payload["absolute_gate_failed"] = bool(payload.get("gate_failed", False))
        payload["gate_mode"] = args.gate_mode
        if baseline:
            payload["baseline_report"] = str(args.baseline_report.expanduser().resolve())
            payload["regression"] = compare_audit_reports(
                baseline,
                payload,
                severity_threshold=SEVERITIES[args.fail_on],
                max_slowdown_ratio=args.max_slowdown,
                min_slowdown_us=int(args.min_slowdown_ms * 1000.0),
            )
            if args.gate_mode == "regression":
                payload["gate_failed"] = bool(payload["regression"]["gate_failed"])
        elif args.gate_mode == "regression":
            raise ValueError("--gate-mode regression requires --baseline-report")
        payload["audit_exit_code"] = 1 if not payload.get("ok", False) else 2 if payload.get("gate_failed", False) else 0
        if args.report:
            payload["report_path"] = str(args.report.expanduser().resolve())
            payload["report_sha256"] = _atomic_json(args.report.expanduser().resolve(), payload)
        output = _summary(payload) if args.summary else payload
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        if not payload.get("ok", False):
            return 1
        return 2 if payload.get("gate_failed", False) else 0
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
