"""Host-independent presentation state for project audit and queue evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Tuple


class ProjectGatePresentationError(ValueError):
    """Raised when project evidence cannot be rendered without guessing."""


@dataclass(frozen=True)
class ProjectGateSceneState:
    source_scene: str
    ok: bool
    gate_failed: bool
    issue_count: int = 0
    atomic_finding_count: int = 0
    report_sha256: str = ""
    queue_status: str = ""
    attempts: int = 0
    error: str = ""

    @property
    def display_name(self) -> str:
        return Path(self.source_scene).stem or "未命名场景"

    @property
    def blocked(self) -> bool:
        return not self.ok or self.gate_failed


@dataclass(frozen=True)
class ProjectGateViewState:
    mode: str
    scenes: Tuple[ProjectGateSceneState, ...]
    identity: str
    guard: str
    verdict: str
    detail: str
    failed: bool = False
    guard_alert: bool = False
    action_text: str = ""
    action_tooltip: str = ""
    action_visible: bool = False
    action_enabled: bool = False


_QUEUE_STATES = frozenset(
    {"待运行", "运行中", "已暂停", "需要重试", "完成", "预检失败"}
)


def _mapping(value, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ProjectGatePresentationError("%s 必须是结构化对象" % label)
    return value


def _count(value, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ProjectGatePresentationError("%s 必须是非负整数" % label) from exc
    if result < 0:
        raise ProjectGatePresentationError("%s 必须是非负整数" % label)
    return result


def _sha(value, label: str, *, required: bool = True) -> str:
    digest = str(value or "")
    if not digest and not required:
        return ""
    if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
        raise ProjectGatePresentationError("%s 不是完整 SHA-256" % label)
    return digest.lower()


def _report_scene(item, index: int) -> ProjectGateSceneState:
    receipt = _mapping(_mapping(item, "场景 %s" % (index + 1)).get("receipt"), "场景回执")
    source_scene = str(receipt.get("source_scene") or "")
    if not source_scene:
        raise ProjectGatePresentationError("场景回执缺少源场景路径")
    return ProjectGateSceneState(
        source_scene=source_scene,
        ok=bool(receipt.get("ok")),
        gate_failed=bool(receipt.get("gate_failed")),
        issue_count=_count(receipt.get("issue_count", 0), "问题数"),
        atomic_finding_count=_count(
            receipt.get("atomic_finding_count", 0), "原子发现数"
        ),
        report_sha256=_sha(receipt.get("report_sha256"), "场景报告签名"),
    )


def present_project_report(payload) -> ProjectGateViewState:
    payload = _mapping(payload, "项目审计包")
    project_sha = _sha(payload.get("project_sha256"), "项目签名")
    summary = _mapping(payload.get("summary"), "项目摘要")
    raw_scenes = tuple(payload.get("scenes") or ())
    scenes = tuple(_report_scene(item, index) for index, item in enumerate(raw_scenes))
    scene_count = _count(summary.get("scene_count"), "场景数")
    passed = _count(summary.get("passed_scene_count"), "通过场景数")
    blocked = _count(summary.get("blocked_scene_count"), "阻断场景数")
    atomic = _count(summary.get("atomic_finding_count"), "原子发现数")
    if scene_count != len(scenes) or passed + blocked != scene_count:
        raise ProjectGatePresentationError("项目摘要与场景回执数量不一致")
    failed = bool(payload.get("gate_failed"))
    if failed != bool(blocked):
        raise ProjectGatePresentationError("项目门禁结论与阻断场景数量不一致")
    return ProjectGateViewState(
        mode="report",
        scenes=scenes,
        identity="项目签名 %s" % project_sha[:12].upper(),
        guard="✓ 双层签名已验证",
        verdict="发布已阻断" if failed else "全项目可以发布",
        detail="%s 个场景 · 通过 %s · 阻断 %s · 原子发现 %s"
        % (scene_count, passed, blocked, atomic),
        failed=failed,
    )


def _queue_scene(job, index: int) -> ProjectGateSceneState:
    job = _mapping(job, "队列任务 %s" % (index + 1))
    source_scene = str(job.get("source_scene") or "")
    if not source_scene:
        raise ProjectGatePresentationError("队列任务缺少源场景路径")
    status = str(job.get("status") or "待运行")
    if status not in {"待运行", "运行中", "通过", "阻断", "失败"}:
        raise ProjectGatePresentationError("未知队列任务状态：%s" % status)
    report_sha = _sha(job.get("report_sha256"), "场景报告签名", required=False)
    return ProjectGateSceneState(
        source_scene=source_scene,
        ok=status != "失败",
        gate_failed=status == "阻断",
        report_sha256=report_sha,
        queue_status=status,
        attempts=_count(job.get("attempts", 0), "尝试次数"),
        error=str(job.get("error") or ""),
    )


def present_project_queue(journal) -> ProjectGateViewState:
    journal = _mapping(journal, "项目队列日志")
    state = str(journal.get("state") or "待运行")
    if state not in _QUEUE_STATES:
        raise ProjectGatePresentationError("未知项目队列状态：%s" % state)
    jobs = tuple(journal.get("jobs") or ())
    scenes = tuple(_queue_scene(job, index) for index, job in enumerate(jobs))
    summary = _mapping(journal.get("summary") or {}, "队列摘要")
    scene_count = _count(summary.get("scene_count", len(scenes)), "场景数")
    passed = _count(summary.get("passed", 0), "通过场景数")
    blocked = _count(summary.get("blocked", 0), "阻断场景数")
    failed_count = _count(summary.get("failed", 0), "失败场景数")
    pending = _count(summary.get("pending", 0), "待运行场景数")
    if scene_count != len(scenes):
        raise ProjectGatePresentationError("队列摘要与任务数量不一致")

    storage = tuple(journal.get("storage_preflight") or ())
    ready = bool(storage) and all(bool(_mapping(item, "容量预检").get("ready")) for item in storage)
    guard_alert = bool(storage) and not ready
    if ready:
        margin = min(
            _count(item.get("free_bytes", 0), "可用容量")
            - _count(item.get("required_bytes", 0), "所需容量")
            for item in storage
        )
        worker = next(
            (
                _mapping(job.get("worker"), "Maya Worker")
                for job in jobs
                if isinstance(job, Mapping) and job.get("worker")
            ),
            None,
        )
        process = ""
        if worker:
            process = " · Maya PID %s · 崩溃联动%s" % (
                worker.get("pid"),
                "开启" if worker.get("job_kill_on_close") else "降级",
            )
        guard = "✓ 容量余量 %.1f GiB%s" % (margin / 1073741824.0, process)
    elif storage:
        guard = "! 磁盘容量预检未通过"
    else:
        guard = "等待所有权与容量预检"

    verdict = {
        "运行中": "项目审计运行中",
        "已暂停": "项目审计已暂停",
        "需要重试": "部分场景需要重试",
        "完成": "项目审计已完成",
        "预检失败": "磁盘容量预检未通过",
    }.get(state, "项目审计待运行")
    if state == "运行中":
        action_text = "安全暂停"
        action_tooltip = "当前场景完成后暂停，不强制终止 Maya"
        action_enabled = True
    elif state in {"已暂停", "需要重试", "待运行", "预检失败"}:
        action_text = "继续队列"
        action_tooltip = "从带签名断点继续，已完成场景不会重复审计"
        action_enabled = True
    else:
        action_text = "打开项目结果"
        action_tooltip = "打开最终双重签名项目审计包"
        action_enabled = bool(journal.get("project_report"))
    journal_sha = _sha(journal.get("journal_sha256"), "断点签名")
    return ProjectGateViewState(
        mode="queue",
        scenes=scenes,
        identity="断点签名 %s · 恢复 %s 次"
        % (journal_sha[:10].upper(), _count(journal.get("recovery_count", 0), "恢复次数")),
        guard=guard,
        verdict=verdict,
        detail="共 %s · 通过 %s · 阻断 %s · 失败 %s · 待运行 %s"
        % (scene_count, passed, blocked, failed_count, pending),
        failed=bool(failed_count) or state == "预检失败",
        guard_alert=guard_alert,
        action_text=action_text,
        action_tooltip=action_tooltip,
        action_visible=True,
        action_enabled=action_enabled,
    )


def present_project_fault(title: str, detail: str) -> ProjectGateViewState:
    title = str(title).strip()
    if not title:
        raise ProjectGatePresentationError("项目队列故障必须包含标题")
    return ProjectGateViewState(
        mode="fault",
        scenes=(),
        identity="队列未取得执行所有权",
        guard="! 已保护现有任务，不会并发启动 Maya",
        verdict=title,
        detail=str(detail).strip()[:120],
        failed=True,
        guard_alert=True,
    )


def empty_project_gate() -> ProjectGateViewState:
    return ProjectGateViewState(
        mode="empty",
        scenes=(),
        identity="等待签名项目包",
        guard="等待所有权与容量预检",
        verdict="尚无项目证据",
        detail="",
    )


__all__ = [
    "ProjectGatePresentationError",
    "ProjectGateSceneState",
    "ProjectGateViewState",
    "empty_project_gate",
    "present_project_fault",
    "present_project_queue",
    "present_project_report",
]
