"""Signed, resumable and strictly serial Maya Scene Clinic audit queue."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
from typing import Callable, Iterable, Mapping
import uuid

from .audit import _atomic_json, _canonical_json, _sha256, run_audit, verify_audit_report
from .project_audit import build_project_audit


PLAN_FORMAT = "mayascope.project-audit-plan"
PLAN_SCHEMA_VERSION = 1
JOURNAL_FORMAT = "mayascope.project-audit-journal"
JOURNAL_SCHEMA_VERSION = 1
FAIL_ON = ("info", "warning", "error", "critical", "never")
DEFAULT_MINIMUM_FREE_BYTES = 512 * 1024 * 1024
DEFAULT_ESTIMATED_REPORT_BYTES = 8 * 1024 * 1024


class QueueBusyError(RuntimeError):
    pass


class InsufficientStorageError(RuntimeError):
    def __init__(self, message: str, evidence=()):
        super().__init__(message)
        self.evidence = tuple(evidence)


_HELD_LOCKS = set()
_HELD_LOCKS_GUARD = threading.Lock()


def _lock_file(stream) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(stream) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read_lock_metadata(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else {}
    except (OSError, ValueError):
        return {}


class QueueLease:
    """Kernel-backed queue ownership; JSON is evidence, not the lock itself."""

    def __init__(self, path: Path, plan_sha256: str, journal_path: Path):
        self.path = path.expanduser().resolve()
        self.metadata_path = self.path.with_suffix(self.path.suffix + ".json")
        self.plan_sha256 = str(plan_sha256)
        self.journal_path = journal_path.expanduser().resolve()
        self.token = uuid.uuid4().hex
        self._stream = None
        self.metadata = {}
        self.previous = {}

    def acquire(self):
        key = os.path.normcase(str(self.path))
        with _HELD_LOCKS_GUARD:
            if key in _HELD_LOCKS:
                owner = _read_lock_metadata(self.metadata_path)
                raise QueueBusyError(
                    "批量审计队列已被当前进程持有：PID %s"
                    % owner.get("pid", os.getpid())
                )
            _HELD_LOCKS.add(key)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stream = open(self.path, "a+b", buffering=0)
            if self.path.stat().st_size == 0:
                stream.write(b" ")
                os.fsync(stream.fileno())
            try:
                _lock_file(stream)
            except OSError as exc:
                stream.close()
                owner = _read_lock_metadata(self.metadata_path)
                raise QueueBusyError(
                    "批量审计队列正由 PID %s / %s 持有，最近心跳 %s"
                    % (
                        owner.get("pid", "未知"), owner.get("host", "未知主机"),
                        owner.get("heartbeat_at", "未知"),
                    )
                ) from exc
            self._stream = stream
            self.previous = _read_lock_metadata(self.metadata_path)
            self.metadata = {
                "format": "mayascope.project-audit-lease",
                "schema_version": 1,
                "token": self.token,
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "plan_sha256": self.plan_sha256,
                "journal_path": str(self.journal_path),
                "state": "已取得所有权",
                "acquired_at": _now(),
                "heartbeat_at": _now(),
                "worker": None,
            }
            self.update()
            return self
        except Exception:
            stream = self._stream
            self._stream = None
            if stream is not None:
                try:
                    _unlock_file(stream)
                except OSError:
                    pass
                stream.close()
            with _HELD_LOCKS_GUARD:
                _HELD_LOCKS.discard(key)
            raise

    def update(self, **fields):
        if self._stream is None:
            raise RuntimeError("队列租约尚未取得")
        self.metadata.update(fields)
        self.metadata["heartbeat_at"] = _now()
        data = (
            json.dumps(self.metadata, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        )
        temporary = self.metadata_path.with_suffix(self.metadata_path.suffix + ".tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(self.metadata_path))

    def recover_previous_worker(self) -> dict | None:
        previous = self.previous or {}
        worker = previous.get("worker") or {}
        identity_payload = worker.get("identity")
        if not identity_payload:
            return None
        from .process_guard import (
            ProcessIdentity, get_process_identity, terminate_exact_process,
        )

        expected = ProcessIdentity.from_dict(identity_payload)
        current = get_process_identity(expected.pid)
        event = {
            "detected_at": _now(),
            "pid": expected.pid,
            "executable": expected.executable,
            "previous_token": previous.get("token", ""),
            "outcome": "进程已退出",
        }
        expected_executable = os.path.normcase(str(Path(worker.get("executable", "")).resolve()))
        identity_executable = os.path.normcase(str(Path(expected.executable).resolve()))
        is_mayapy = Path(expected.executable).name.lower() in {"mayapy", "mayapy.exe"}
        same_queue = (
            previous.get("plan_sha256") == self.plan_sha256
            and os.path.normcase(str(Path(previous.get("journal_path", "")).resolve()))
            == os.path.normcase(str(self.journal_path))
        )
        if not is_mayapy or expected_executable != identity_executable or not same_queue:
            event["outcome"] = "身份边界不匹配，未执行终止"
            self.update(recovery_event=event)
            return event
        if current is not None:
            if current != expected:
                event["outcome"] = "PID 已复用，未执行终止"
            else:
                terminated = terminate_exact_process(expected, timeout=5.0)
                event["outcome"] = "已终止验证孤儿" if terminated else "孤儿已自行退出"
        self.update(recovery_event=event)
        return event

    def release(self):
        if self._stream is None:
            return
        key = os.path.normcase(str(self.path))
        try:
            self.update(state="已释放", worker=None, released_at=_now())
            _unlock_file(self._stream)
        finally:
            self._stream.close()
            self._stream = None
            with _HELD_LOCKS_GUARD:
                _HELD_LOCKS.discard(key)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback):
        self.release()


def _volume_key(path: Path) -> str:
    resolved = path.expanduser().resolve()
    return os.path.normcase(resolved.anchor or os.sep)


def preflight_storage(
    plan: Mapping,
    journal_path: Path,
    report_dir: Path,
    project_report: Path | None,
    pending_count: int,
) -> tuple:
    settings = plan["settings"]
    reserve = int(settings.get("minimum_free_bytes", DEFAULT_MINIMUM_FREE_BYTES))
    per_scene = int(settings.get("estimated_report_bytes", DEFAULT_ESTIMATED_REPORT_BYTES))
    if reserve < 0 or per_scene < 0:
        raise ValueError("磁盘预检预算不能为负数")
    output_required = reserve + max(1, int(pending_count)) * per_scene
    temp_required = reserve + per_scene
    targets = [
        (journal_path.expanduser().resolve().parent, output_required, "断点日志"),
        (report_dir.expanduser().resolve(), output_required, "场景报告"),
        (Path(tempfile.gettempdir()).resolve(), temp_required, "隐藏 Maya 临时目录"),
    ]
    if project_report is not None:
        targets.append((project_report.expanduser().resolve().parent, output_required, "项目报告"))
    grouped = {}
    for path, required, role in targets:
        existing = path
        while not existing.exists() and existing.parent != existing:
            existing = existing.parent
        key = _volume_key(existing)
        item = grouped.setdefault(key, {"path": str(existing), "required_bytes": 0, "roles": []})
        item["required_bytes"] = max(item["required_bytes"], required)
        item["roles"].append(role)
    evidence = []
    for key in sorted(grouped):
        item = grouped[key]
        usage = shutil.disk_usage(item["path"])
        record = {
            "volume": key,
            "path": item["path"],
            "roles": tuple(sorted(set(item["roles"]))),
            "free_bytes": int(usage.free),
            "total_bytes": int(usage.total),
            "required_bytes": int(item["required_bytes"]),
            "ready": int(usage.free) >= int(item["required_bytes"]),
        }
        evidence.append(record)
    failed = [item for item in evidence if not item["ready"]]
    if failed:
        item = failed[0]
        raise InsufficientStorageError(
            "磁盘空间不足：%s 可用 %.1f MiB，需要至少 %.1f MiB"
            % (
                item["volume"], item["free_bytes"] / 1048576.0,
                item["required_bytes"] / 1048576.0,
            ),
            evidence,
        )
    return tuple(evidence)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _signed(payload: Mapping, field: str) -> dict:
    envelope = dict(payload)
    envelope.pop(field, None)
    envelope[field] = hashlib.sha256(_canonical_json(envelope)).hexdigest()
    return envelope


def _atomic_signed(path: Path, payload: Mapping, field: str) -> str:
    destination = path.expanduser().resolve()
    envelope = _signed(payload, field)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    data = json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(destination))
    return envelope[field]


def _verify_signed(path: Path, *, format_name: str, schema: int, field: str) -> dict:
    source = path.expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("format") != format_name:
        raise ValueError("文件格式不属于 MayaScope 批量审计")
    if payload.get("schema_version") != schema:
        raise ValueError("不支持的批量审计格式版本")
    expected = payload.pop(field, None)
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("批量审计文件缺少有效签名")
    actual = hashlib.sha256(_canonical_json(payload)).hexdigest()
    if actual != expected:
        raise ValueError("批量审计文件签名不匹配")
    payload[field] = expected
    return payload


def create_project_plan(
    scenes: Iterable[Path],
    output: Path | None = None,
    *,
    profile: str = "publish",
    fail_on: str = "error",
    config: Path | None = None,
    workspace: Path | None = None,
    mayapy: Path | None = None,
    timeout: float = 300.0,
    minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES,
    estimated_report_bytes: int = DEFAULT_ESTIMATED_REPORT_BYTES,
) -> dict:
    if fail_on not in FAIL_ON:
        raise ValueError("未知严重级门槛：%s" % fail_on)
    if timeout <= 0:
        raise ValueError("单场景超时必须大于零")
    if minimum_free_bytes < 0 or estimated_report_bytes < 0:
        raise ValueError("磁盘预检预算不能为负数")
    config_path = config.expanduser().resolve() if config else None
    if config_path and not config_path.is_file():
        raise ValueError("Clinic 配置文件不存在")
    workspace_path = workspace.expanduser().resolve() if workspace else None
    if workspace_path and not workspace_path.is_dir():
        raise ValueError("项目工作区不存在")
    mayapy_path = mayapy.expanduser().resolve() if mayapy else None
    if mayapy_path and not mayapy_path.is_file():
        raise ValueError("mayapy 路径不存在")
    jobs = []
    seen = set()
    for scene in scenes:
        source = Path(scene).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in {".ma", ".mb"}:
            raise ValueError("批量审计只接受现有 .ma 或 .mb 场景：%s" % source)
        identity = os.path.normcase(str(source))
        if identity in seen:
            raise ValueError("批量审计计划包含重复场景：%s" % source)
        seen.add(identity)
        source_sha = _sha256(source)
        jobs.append({
            "id": hashlib.sha256((identity + "\0" + source_sha).encode("utf-8")).hexdigest()[:20],
            "source_scene": str(source),
            "source_sha256": source_sha,
        })
    if not jobs:
        raise ValueError("批量审计计划至少需要一个场景")
    jobs.sort(key=lambda item: os.path.normcase(item["source_scene"]))
    payload = {
        "format": PLAN_FORMAT,
        "schema_version": PLAN_SCHEMA_VERSION,
        "settings": {
            "profile": profile,
            "fail_on": fail_on,
            "config": str(config_path) if config_path else "",
            "config_sha256": _sha256(config_path) if config_path else "",
            "workspace": str(workspace_path) if workspace_path else "",
            "mayapy": str(mayapy_path) if mayapy_path else "",
            "timeout": float(timeout),
            "minimum_free_bytes": int(minimum_free_bytes),
            "estimated_report_bytes": int(estimated_report_bytes),
        },
        "jobs": jobs,
    }
    signed = _signed(payload, "plan_sha256")
    if output is not None:
        _atomic_signed(output, signed, "plan_sha256")
    return signed


def verify_project_plan(path: Path) -> dict:
    payload = _verify_signed(
        path, format_name=PLAN_FORMAT, schema=PLAN_SCHEMA_VERSION, field="plan_sha256"
    )
    jobs = payload.get("jobs") or ()
    if not jobs:
        raise ValueError("批量审计计划没有场景")
    identities = [os.path.normcase(str(item.get("source_scene") or "")) for item in jobs]
    if any(not value for value in identities) or len(identities) != len(set(identities)):
        raise ValueError("批量审计计划存在空场景或重复场景")
    expected = sorted(identities)
    if identities != expected:
        raise ValueError("批量审计计划场景顺序不是确定性的")
    return payload


def _new_journal(plan: Mapping) -> dict:
    return {
        "format": JOURNAL_FORMAT,
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "plan_sha256": plan["plan_sha256"],
        "state": "待运行",
        "created_at": _now(),
        "updated_at": _now(),
        "recovery_count": 0,
        "jobs": [
            {
                **job,
                "status": "待运行",
                "attempts": 0,
                "report_path": "",
                "report_sha256": "",
                "error": "",
                "started_at": "",
                "completed_at": "",
                "worker": None,
            }
            for job in plan["jobs"]
        ],
    }


def verify_queue_journal(path: Path, plan: Mapping | None = None) -> dict:
    payload = _verify_signed(
        path, format_name=JOURNAL_FORMAT, schema=JOURNAL_SCHEMA_VERSION,
        field="journal_sha256",
    )
    if plan is not None and payload.get("plan_sha256") != plan.get("plan_sha256"):
        raise ValueError("断点日志不属于当前批量审计计划")
    for job in payload.get("jobs") or ():
        if job.get("status") in {"通过", "阻断"}:
            report_path = Path(str(job.get("report_path") or ""))
            report = verify_audit_report(report_path)
            if report.get("report_sha256") != job.get("report_sha256"):
                raise ValueError("断点日志中的场景报告签名不一致")
            if os.path.normcase(str(Path(report["source_scene"]).resolve())) != os.path.normcase(
                str(Path(job["source_scene"]).resolve())
            ):
                raise ValueError("断点日志中的场景报告来源不一致")
    return payload


def _report_name(index: int, job: Mapping) -> str:
    stem = Path(job["source_scene"]).stem
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in stem)[:48]
    return "%04d-%s-%s.audit.json" % (index, safe or "scene", job["id"][:8])


def _write_worker_report(path: Path, payload: Mapping) -> dict:
    report = dict(payload)
    report["absolute_gate_failed"] = bool(report.get("gate_failed", False))
    report["gate_mode"] = "absolute"
    report["audit_exit_code"] = (
        1 if not report.get("ok", False) else 2 if report.get("gate_failed", False) else 0
    )
    report["report_path"] = str(path.expanduser().resolve())
    report["report_sha256"] = _atomic_json(path.expanduser().resolve(), report)
    return report


def _run_project_plan_locked(
    plan: Mapping,
    journal_path: Path,
    report_dir: Path,
    project_report: Path | None = None,
    *,
    should_cancel: Callable[[], bool] | None = None,
    progress: Callable[[Mapping], None] | None = None,
    max_scenes: int | None = None,
    lease: QueueLease,
    recovery_event: Mapping | None = None,
) -> dict:
    journal_file = journal_path.expanduser().resolve()
    reports_root = report_dir.expanduser().resolve()
    if journal_file.is_file():
        journal = verify_queue_journal(journal_file, plan)
        recovered = False
        for job in journal["jobs"]:
            if job["status"] == "运行中":
                job["status"] = "待运行"
                job["error"] = "上次运行中断，已安全恢复到待运行"
                recovered = True
            elif job["status"] == "失败":
                job["status"] = "待运行"
                recovered = True
        if recovered:
            journal["recovery_count"] = int(journal.get("recovery_count", 0)) + 1
    else:
        journal = _new_journal(plan)
    if recovery_event:
        journal.setdefault("recovery_events", []).append(dict(recovery_event))
        journal["recovery_count"] = int(journal.get("recovery_count", 0)) + 1
    if [job["id"] for job in journal["jobs"]] != [job["id"] for job in plan["jobs"]]:
        raise ValueError("断点日志的任务清单与计划不一致")

    settings = plan["settings"]
    config = Path(settings["config"]) if settings.get("config") else None
    if config and _sha256(config) != settings.get("config_sha256"):
        raise ValueError("Clinic 配置在计划创建后发生变化")
    workspace = Path(settings["workspace"]) if settings.get("workspace") else None
    mayapy = Path(settings["mayapy"]) if settings.get("mayapy") else None
    cancelled = should_cancel or (lambda: False)
    processed = 0

    def persist(state: str):
        journal["state"] = state
        journal["updated_at"] = _now()
        journal["summary"] = {
            "scene_count": len(journal["jobs"]),
            "pending": sum(item["status"] == "待运行" for item in journal["jobs"]),
            "running": sum(item["status"] == "运行中" for item in journal["jobs"]),
            "passed": sum(item["status"] == "通过" for item in journal["jobs"]),
            "blocked": sum(item["status"] == "阻断" for item in journal["jobs"]),
            "failed": sum(item["status"] == "失败" for item in journal["jobs"]),
        }
        journal["journal_sha256"] = _atomic_signed(
            journal_file, journal, "journal_sha256"
        )
        active = next(
            (item["id"] for item in journal["jobs"] if item["status"] == "运行中"),
            "",
        )
        lease.update(
            state=state,
            journal_sha256=journal["journal_sha256"],
            active_job_id=active,
        )
        if progress:
            progress(json.loads(json.dumps(journal, ensure_ascii=False)))

    pending_count = sum(job["status"] == "待运行" for job in journal["jobs"])
    try:
        journal["storage_preflight"] = preflight_storage(
            plan, journal_file, reports_root, project_report, pending_count
        )
    except InsufficientStorageError as exc:
        journal["storage_preflight"] = exc.evidence
        persist("预检失败")
        raise
    reports_root.mkdir(parents=True, exist_ok=True)
    persist("运行中")
    for index, job in enumerate(journal["jobs"]):
        if job["status"] in {"通过", "阻断"}:
            continue
        if cancelled() or (max_scenes is not None and processed >= max_scenes):
            persist("已暂停")
            return journal
        source = Path(job["source_scene"])
        if not source.is_file() or _sha256(source) != job["source_sha256"]:
            job["status"] = "失败"
            job["error"] = "源场景不存在或内容已改变"
            job["completed_at"] = _now()
            processed += 1
            persist("运行中")
            continue
        job["status"] = "运行中"
        job["attempts"] = int(job.get("attempts", 0)) + 1
        job["started_at"] = _now()
        job["completed_at"] = ""
        job["error"] = ""
        persist("运行中")
        try:
            def process_started(event):
                job["worker"] = dict(event)
                lease.update(worker=dict(event), active_job_id=job["id"], state="运行中")
                persist("运行中")

            def process_finished(event):
                job["worker"] = None
                lease.update(worker=None, active_job_id=job["id"], state="运行中")

            raw = run_audit(
                source,
                profile=settings["profile"],
                fail_on=settings["fail_on"],
                mayapy=mayapy,
                config=config,
                workspace=workspace,
                timeout=float(settings["timeout"]),
                process_started=process_started,
                process_finished=process_finished,
            )
            report_path = reports_root / _report_name(index, job)
            report = _write_worker_report(report_path, raw)
            job["report_path"] = str(report_path)
            job["report_sha256"] = report["report_sha256"]
            job["status"] = "阻断" if report.get("gate_failed") else "通过"
        except Exception as exc:
            job["status"] = "失败"
            job["error"] = "%s: %s" % (type(exc).__name__, exc)
        job["worker"] = None
        job["completed_at"] = _now()
        processed += 1
        persist("运行中")

    failed = any(job["status"] == "失败" for job in journal["jobs"])
    pending = any(job["status"] == "待运行" for job in journal["jobs"])
    if failed or pending:
        persist("需要重试" if failed else "已暂停")
        return journal
    if project_report is not None:
        report_paths = [Path(job["report_path"]) for job in journal["jobs"]]
        bundle = build_project_audit(report_paths, project_report)
        journal["project_report"] = str(project_report.expanduser().resolve())
        journal["project_sha256"] = bundle["project_sha256"]
    persist("完成")
    return journal


def run_project_plan(
    plan_path: Path,
    journal_path: Path,
    report_dir: Path,
    project_report: Path | None = None,
    *,
    should_cancel: Callable[[], bool] | None = None,
    progress: Callable[[Mapping], None] | None = None,
    max_scenes: int | None = None,
) -> dict:
    plan = verify_project_plan(plan_path)
    journal_file = journal_path.expanduser().resolve()
    lock_path = journal_file.with_suffix(journal_file.suffix + ".lock")
    with QueueLease(lock_path, plan["plan_sha256"], journal_file) as lease:
        recovery_event = lease.recover_previous_worker()
        return _run_project_plan_locked(
            plan,
            journal_file,
            report_dir,
            project_report,
            should_cancel=should_cancel,
            progress=progress,
            max_scenes=max_scenes,
            lease=lease,
            recovery_event=recovery_event,
        )


def _exit_code(journal: Mapping) -> int:
    if journal.get("state") != "完成":
        return 1
    return 2 if any(job.get("status") == "阻断" for job in journal.get("jobs") or ()) else 0


def _summary(journal: Mapping) -> dict:
    return {
        "state": journal.get("state"),
        "journal_sha256": journal.get("journal_sha256"),
        "project_sha256": journal.get("project_sha256"),
        **dict(journal.get("summary") or {}),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mayascope-project-queue")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="创建带签名的批量审计计划")
    create.add_argument("scenes", type=Path, nargs="+")
    create.add_argument("--plan", type=Path, required=True)
    create.add_argument("--profile", default="publish")
    create.add_argument("--fail-on", choices=FAIL_ON, default="error")
    create.add_argument("--config", type=Path)
    create.add_argument("--workspace", type=Path)
    create.add_argument("--mayapy", type=Path)
    create.add_argument("--timeout", type=float, default=300.0)
    create.add_argument("--minimum-free-mib", type=float, default=512.0)
    create.add_argument("--estimated-report-mib", type=float, default=8.0)
    run = commands.add_parser("run", help="串行执行或恢复批量审计")
    run.add_argument("plan", type=Path)
    run.add_argument("--journal", type=Path, required=True)
    run.add_argument("--report-dir", type=Path, required=True)
    run.add_argument("--project-report", type=Path, required=True)
    run.add_argument("--max-scenes", type=int)
    verify = commands.add_parser("verify", help="校验计划或断点日志")
    verify.add_argument("path", type=Path)
    verify.add_argument("--plan", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            payload = create_project_plan(
                args.scenes, args.plan, profile=args.profile, fail_on=args.fail_on,
                config=args.config, workspace=args.workspace, mayapy=args.mayapy,
                timeout=args.timeout,
                minimum_free_bytes=int(args.minimum_free_mib * 1048576.0),
                estimated_report_bytes=int(args.estimated_report_mib * 1048576.0),
            )
            output = {"scene_count": len(payload["jobs"]), "plan_sha256": payload["plan_sha256"]}
            exit_code = 0
        elif args.command == "run":
            payload = run_project_plan(
                args.plan, args.journal, args.report_dir, args.project_report,
                max_scenes=args.max_scenes,
            )
            output = _summary(payload)
            exit_code = _exit_code(payload)
        else:
            raw = json.loads(args.path.read_text(encoding="utf-8"))
            if raw.get("format") == PLAN_FORMAT:
                payload = verify_project_plan(args.path)
                output = {"scene_count": len(payload["jobs"]), "plan_sha256": payload["plan_sha256"]}
            else:
                plan = verify_project_plan(args.plan) if args.plan else None
                payload = verify_queue_journal(args.path, plan)
                output = _summary(payload)
            exit_code = 0
        print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return exit_code
    except Exception as exc:
        print(json.dumps(
            {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
