"""Time-sliced Maya 2025 execution-surface inventory."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import time
from typing import Any, List, Optional, Tuple

from ..model import (
    RuntimeExpression,
    RuntimeNodeCallbacks,
    RuntimePlugin,
    RuntimeScriptJob,
    RuntimeSnapshot,
    SceneSnapshot,
)


class RuntimeChangedDuringCapture(RuntimeError):
    pass


class RuntimeCaptureCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeCaptureProgress:
    stage: str
    completed: int
    total: int


_JOB_LINE = re.compile(r"^\s*(\d+)\s*:\s*(.*)$")
_TRIGGERS = (
    ("event", re.compile(r'(?:^|\s)-(?:e|event)\s+["\']?([^"\'\s]+)')),
    ("condition", re.compile(r'(?:^|\s)-(?:cc|cf|ct|conditionChange|conditionFalse|conditionTrue)\s+["\']?([^"\'\s]+)')),
    ("attribute", re.compile(r'(?:^|\s)-(?:ac|aa|ad|attributeChange|attributeAdded|attributeDeleted)\s+["\']?([^"\']+)')),
    ("connection", re.compile(r'(?:^|\s)-(?:con|connectionChange)\s+["\']?([^"\']+)')),
    ("idle", re.compile(r'(?:^|\s)-(?:ie|idleEvent)(?:\s|$)')),
    ("time", re.compile(r'(?:^|\s)-(?:tc|timeChange)(?:\s|$)')),
    ("ui", re.compile(r'(?:^|\s)-(?:uid|uiDeleted)\s+["\']?([^"\']+)')),
)


def _safe(callable_, default=None):
    try:
        return callable_()
    except Exception:
        return default


def _preview(value: str, limit: int = 180) -> str:
    return " ".join(str(value).replace("\x00", "").split())[:limit]


def parse_script_job(value: str) -> RuntimeScriptJob:
    match = _JOB_LINE.match(str(value))
    if not match:
        raise ValueError("Unrecognized Maya scriptJob descriptor")
    job_id = int(match.group(1))
    descriptor = match.group(2).strip()
    trigger_kind, trigger = "other", ""
    for kind, pattern in _TRIGGERS:
        found = pattern.search(descriptor)
        if found:
            trigger_kind = kind
            trigger = found.group(1) if found.lastindex else kind
            break
    tokens = set(descriptor.split())
    return RuntimeScriptJob(
        job_id=job_id,
        trigger_kind=trigger_kind,
        trigger=trigger,
        protected=bool(tokens.intersection({"-pro", "-protected"})),
        permanent=bool(tokens.intersection({"-per", "-permanent"})),
        kill_with_scene=bool(tokens.intersection({"-kws", "-killWithScene"})),
        descriptor_sha256=hashlib.sha256(descriptor.encode("utf-8", "replace")).hexdigest(),
        descriptor_preview=_preview(descriptor),
    )


class MayaRuntimeCaptureSession:
    def __init__(self, snapshot: SceneSnapshot, cmds_module=None, om_module=None):
        if cmds_module is None or om_module is None:
            import maya.api.OpenMaya as om_module  # type: ignore
            import maya.cmds as cmds_module  # type: ignore
        self.snapshot = snapshot
        self.cmds = cmds_module
        self.om = om_module
        self.batch_mode = bool(_safe(lambda: self.cmds.about(batch=True), True))
        raw_jobs = _safe(lambda: self.cmds.scriptJob(listJobs=True), None)
        self.script_jobs_available = not self.batch_mode
        self._raw_jobs = tuple(str(item) for item in (raw_jobs or ()))
        self._expression_names = tuple(sorted(_safe(lambda: self.cmds.ls(type="expression"), ()) or ()))
        self._plugin_names = tuple(sorted(_safe(lambda: self.cmds.pluginInfo(query=True, listPlugins=True), ()) or ()))
        self._callback_nodes = tuple(
            (node, node.dag_paths[0] if node.dag_paths else node.name)
            for node in snapshot.nodes
        )
        self._node_by_name = {node.name: node for node in snapshot.nodes}
        self.expressions: List[RuntimeExpression] = []
        self.plugins: List[RuntimePlugin] = []
        self.callbacks: List[RuntimeNodeCallbacks] = []
        self.stage = "expressions"
        self._index = 0
        self._result: Optional[RuntimeSnapshot] = None
        self._cancelled = False
        self._topology_changed = False
        self._guards = []

        def changed(*_args):
            self._topology_changed = True

        try:
            self._guards = [
                self.om.MDGMessage.addNodeAddedCallback(changed, "dependNode"),
                self.om.MDGMessage.addNodeRemovedCallback(changed, "dependNode"),
            ]
        except Exception:
            self._remove_guards()
            raise

    def _remove_guards(self):
        if self._guards:
            _safe(lambda: self.om.MMessage.removeCallbacks(self._guards), None)
            self._guards = []

    def __del__(self):
        self._remove_guards()

    @property
    def done(self):
        return self.stage == "done"

    @property
    def result(self):
        if self._result is None:
            raise RuntimeError("Runtime capture has not completed")
        return self._result

    def cancel(self):
        self._cancelled = True
        self._remove_guards()

    def _step_expression(self):
        if self._index >= len(self._expression_names):
            self.stage, self._index = "plugins", 0
            return
        name = self._expression_names[self._index]
        self._index += 1
        source = str(_safe(lambda: self.cmds.expression(name, query=True, string=True), "") or "")
        node = self._node_by_name.get(name)
        self.expressions.append(
            RuntimeExpression(
                node_id=node.id if node else "",
                node_name=name,
                object_name=str(_safe(lambda: self.cmds.expression(name, query=True, object=True), "") or ""),
                always_evaluate=bool(_safe(lambda: self.cmds.expression(name, query=True, alwaysEvaluate=True), False)),
                unit_conversion=str(_safe(lambda: self.cmds.expression(name, query=True, unitConversion=True), "") or ""),
                source_sha256=hashlib.sha256(source.encode("utf-8", "replace")).hexdigest(),
                source_length=len(source),
                source_preview=_preview(source),
                referenced=bool(node.referenced if node else False),
            )
        )

    def _step_plugin(self):
        if self._index >= len(self._plugin_names):
            self.stage, self._index = "callbacks", 0
            return
        name = self._plugin_names[self._index]
        self._index += 1
        query = lambda flag, default=None: _safe(
            lambda: self.cmds.pluginInfo(name, query=True, **{flag: True}), default
        )
        self.plugins.append(
            RuntimePlugin(
                name=name,
                path=str(query("path", "") or ""),
                vendor=str(query("vendor", "") or ""),
                version=str(query("version", "") or ""),
                api_version=str(query("apiVersion", "") or ""),
                autoload=bool(query("autoload", False)),
                unload_ok=bool(query("unloadOk", False)),
                node_types=tuple(str(item) for item in (query("dependNode", ()) or ())),
                commands=tuple(str(item) for item in (query("command", ()) or ())),
            )
        )

    def _step_callback(self):
        if self._index >= len(self._callback_nodes):
            self.stage, self._index = "verify", 0
            return
        node, lookup_name = self._callback_nodes[self._index]
        self._index += 1
        selection = self.om.MSelectionList()
        try:
            selection.add(lookup_name)
            obj = selection.getDependNode(0)
            count = len(self.om.MMessage.nodeCallbacks(obj))
        except Exception:
            return
        if count:
            self.callbacks.append(RuntimeNodeCallbacks(node.id, node.name, count))

    def _verify(self):
        jobs = tuple(str(item) for item in (_safe(lambda: self.cmds.scriptJob(listJobs=True), None) or ()))
        expressions = tuple(sorted(_safe(lambda: self.cmds.ls(type="expression"), ()) or ()))
        plugins = tuple(sorted(_safe(lambda: self.cmds.pluginInfo(query=True, listPlugins=True), ()) or ()))
        current_scene = str(_safe(lambda: self.cmds.file(query=True, sceneName=True), "") or "")
        if (
            self._topology_changed
            or current_scene != self.snapshot.source_scene
            or jobs != self._raw_jobs
            or expressions != self._expression_names
            or plugins != self._plugin_names
        ):
            self._remove_guards()
            raise RuntimeChangedDuringCapture("Runtime execution surface changed during capture")
        self.stage = "finalize"

    def _finalize(self):
        parsed_jobs = []
        parse_failures = []
        for raw in self._raw_jobs:
            try:
                parsed_jobs.append(parse_script_job(raw))
            except ValueError:
                parse_failures.append(_preview(raw))
        self._result = RuntimeSnapshot(
            source_snapshot_id=self.snapshot.snapshot_id,
            script_jobs=tuple(parsed_jobs),
            expressions=tuple(self.expressions),
            plugins=tuple(self.plugins),
            node_callbacks=tuple(self.callbacks),
            script_jobs_available=self.script_jobs_available,
            batch_mode=self.batch_mode,
            maya_version=str(_safe(lambda: self.cmds.about(version=True), "") or ""),
            metadata={
                "script_job_parse_failures": tuple(parse_failures),
                "callback_nodes_scanned": len(self._callback_nodes),
            },
        )
        self.stage = "done"
        self._remove_guards()

    def progress(self):
        totals = {
            "expressions": len(self._expression_names),
            "plugins": len(self._plugin_names),
            "callbacks": len(self._callback_nodes),
            "verify": 1,
            "finalize": 1,
            "done": 1,
        }
        return RuntimeCaptureProgress(self.stage, self._index, totals[self.stage])

    def step(self, max_items=128, max_milliseconds=7.0):
        if self._cancelled:
            self._remove_guards()
            raise RuntimeCaptureCancelled("Runtime capture cancelled")
        deadline = time.perf_counter() + max_milliseconds / 1000.0
        count = 0
        while not self.done and count < max_items and time.perf_counter() < deadline:
            if self._cancelled:
                self._remove_guards()
                raise RuntimeCaptureCancelled("Runtime capture cancelled")
            if self.stage == "expressions":
                self._step_expression()
            elif self.stage == "plugins":
                self._step_plugin()
            elif self.stage == "callbacks":
                self._step_callback()
            elif self.stage == "verify":
                self._verify()
            elif self.stage == "finalize":
                self._finalize()
            count += 1
        return self.progress()


def capture_runtime(snapshot, cmds_module=None, om_module=None):
    session = MayaRuntimeCaptureSession(snapshot, cmds_module, om_module)
    while not session.done:
        session.step(max_items=2048, max_milliseconds=1000.0)
    return session.result
