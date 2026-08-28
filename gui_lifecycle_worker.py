"""In-Maya worker for the isolated GUI lifecycle probe.

This module is imported by a Maya GUI process created and owned by
``MayaScope.gui_lifecycle``.  It uses the real product entry point and exits
the owned host when the bounded probe finishes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import traceback


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(str(temporary), str(path))


def schedule() -> None:
    from PySide6 import QtCore, QtWidgets
    from maya import cmds

    class Probe(QtCore.QObject):
        def __init__(self):
            super().__init__()
            self.started = time.perf_counter()
            self.deadline = self.started + 70.0
            self.output = Path(os.environ["MAYASCOPE_GUI_LIFECYCLE_WORKER"])
            self.screenshot = Path(os.environ["MAYASCOPE_GUI_LIFECYCLE_SCREENSHOT"])
            self.checks = {}
            self.scenario = os.environ.get(
                "MAYASCOPE_GUI_LIFECYCLE_SCENARIO", "default"
            )
            self.window_size = (
                int(os.environ.get("MAYASCOPE_GUI_LIFECYCLE_WIDTH", "1480")),
                int(os.environ.get("MAYASCOPE_GUI_LIFECYCLE_HEIGHT", "900")),
            )
            self.first = None
            self.second = None
            self.third = None

        def later(self, callback, milliseconds=250):
            QtCore.QTimer.singleShot(milliseconds, lambda: self.guard(callback))

        def guard(self, callback):
            try:
                if time.perf_counter() > self.deadline:
                    raise TimeoutError("真实 Maya GUI 生命周期探针超时")
                callback()
            except Exception as exc:
                self.finish_error(exc)

        def visible_workspaces(self):
            return tuple(
                widget
                for widget in QtWidgets.QApplication.allWidgets()
                if widget.objectName() == "MayaScopeSpectralWorkspace" and widget.isVisible()
            )

        @staticmethod
        def ready(window):
            return (
                window is not None
                and window.isVisible()
                and window._snapshot is not None
                and window._capture_session is None
                and window._clinic_thread is None
            )

        def wait_ready(self, window, callback):
            if self.ready(window):
                callback()
            else:
                self.later(lambda: self.wait_ready(window, callback), 150)

        def start(self):
            import MayaScope
            from MayaScope import __version__, launch

            self.launch = launch
            self.version = __version__
            self.package_root = str(Path(MayaScope.__file__).resolve().parent)
            expected = os.environ.get("MAYASCOPE_EXPECTED_PACKAGE_ROOT", "")
            if expected:
                expected = str(Path(expected).resolve())
                self.checks["发布包来源"] = {
                    "实际包目录": self.package_root,
                    "预期包目录": expected,
                    "通过": os.path.normcase(self.package_root) == os.path.normcase(expected),
                }
            self.first = launch.run("workspace")
            self.first.resize(*self.window_size)
            self.wait_ready(self.first, self.after_first)

        def after_first(self):
            if self.scenario == "instruments":
                self.prepare_instrument_scenario()
            elif self.scenario == "runtime-cancel":
                self.prepare_runtime_cancel_scenario()
            elif self.scenario == "project-gate":
                self.prepare_project_gate_scenario()
            self.screenshot.parent.mkdir(parents=True, exist_ok=True)
            saved = bool(self.first.grab().save(str(self.screenshot)))
            parent = self.first.parentWidget()
            host_parent = parent.objectName() if parent is not None else ""
            first_passed = bool(
                self.first.isVisible()
                and self.first._snapshot is not None
                and host_parent == "MayaWindow"
                and saved
            )
            self.checks["首次启动"] = {
                "通过": first_passed,
                "窗口标题": self.first.windowTitle(),
                "对象名": self.first.objectName(),
                "宿主父窗口": host_parent,
                "真实 Maya 父窗口": host_parent == "MayaWindow",
                "快照节点": len(self.first._snapshot.nodes),
                "中文界面": "光谱因果场景图谱" in self.first.windowTitle(),
                "真实绘制截图": saved and self.screenshot.is_file(),
                "选择回调运行": bool(
                    self.first._selection_bridge and self.first._selection_bridge.active
                ),
            }
            if self.scenario == "instruments":
                self.verify_instrument_clear()
            elif self.scenario == "runtime-cancel":
                self.verify_runtime_cancel()
            old = self.first
            self.second = self.launch.run("workspace")
            self.second.resize(*self.window_size)
            self.checks["重复启动清理"] = {
                "旧窗口已隐藏": not old.isVisible(),
                "创建新实例": self.second is not old,
            }
            self.wait_ready(self.second, self.after_second)

        def prepare_instrument_scenario(self):
            from MayaScope.analysis.runtime import analyze_runtime
            from MayaScope.collectors import (
                MayaRuntimeCaptureSession,
                profile_callable,
            )

            snapshot = self.first._snapshot

            def operation():
                cmds.dgdirty(allPlugs=True)
                cmds.refresh(force=True)

            profiler = profile_callable(operation, snapshot=snapshot).capture
            transition = self.first._investigation.accept_profiler(
                self.first._presentation,
                profiler,
            )
            self.first._apply_investigation_transition(transition)
            self.first.pulse.set_capture(profiler)

            session = MayaRuntimeCaptureSession(snapshot)
            while not session.done:
                session.step(max_items=512, max_milliseconds=25.0)
            runtime = session.result
            report = analyze_runtime(runtime, snapshot)
            transition = self.first._investigation.accept_runtime(
                self.first._presentation,
                runtime,
                report,
            )
            self.first._apply_investigation_transition(transition)
            self.first.runtime_constellation.set_report(runtime, report)
            self.first.clinic_view.set_heading("性能与运行时证据")
            self.first.clinic_view.set_body(
                "真实 Maya Profiler\n"
                "%s 个事件 · %s 个节点事件已映射 · %.2f ms\n\n"
                "运行时执行表面\n"
                "%s 个表达式 · %s 个 scriptJob · %s 个插件 · %s 个回调节点\n\n"
                "可拖选时间窗；清除采样只会移除调查证据，不会修改 Maya 场景。"
                % (
                    len(profiler.events),
                    profiler.mapped_event_count,
                    profiler.duration_us / 1000.0,
                    len(runtime.expressions),
                    len(runtime.script_jobs),
                    len(runtime.plugins),
                    len(runtime.node_callbacks),
                )
            )
            self.first.clinic_view.set_action("只读证据 · 场景未修改", enabled=False)
            self.first.status.setText(
                "  仪器验收  ·  真实 Profiler 与 Runtime 采集完成  ·  场景未修改"
            )
            QtWidgets.QApplication.processEvents()
            self.checks["真实仪器场景"] = {
                "通过": bool(profiler.events and runtime.source_snapshot_id == snapshot.snapshot_id),
                "Profiler 事件": len(profiler.events),
                "已映射节点事件": profiler.mapped_event_count,
                "Runtime 信号": len(report.issues),
                "清除采样可见": not self.first.pulse.clear_button.isHidden(),
                "场景代次一致": runtime.source_snapshot_id == snapshot.snapshot_id,
            }
            self.instrument_modified_before_clear = bool(
                cmds.file(query=True, modified=True)
            )
            self.instrument_runtime = runtime

        def verify_instrument_clear(self):
            self.first._dismiss_profiler()
            QtWidgets.QApplication.processEvents()
            modified_after = bool(cmds.file(query=True, modified=True))
            self.checks["清除采样恢复"] = {
                "通过": bool(
                    self.first._profiler_capture is None
                    and self.first._counterfactual_run is None
                    and self.first._runtime_snapshot is self.instrument_runtime
                    and self.first.pulse.clear_button.isHidden()
                    and modified_after == self.instrument_modified_before_clear
                ),
                "Profiler 已清除": self.first._profiler_capture is None,
                "派生反事实已失效": self.first._counterfactual_run is None,
                "Runtime 证据仍保留": self.first._runtime_snapshot is self.instrument_runtime,
                "清除按钮已归位": self.first.pulse.clear_button.isHidden(),
                "Maya 修改状态未改变": modified_after == self.instrument_modified_before_clear,
            }

        def prepare_runtime_cancel_scenario(self):
            self.runtime_before_cancel = self.first._runtime_snapshot
            self.runtime_modified_before_cancel = bool(
                cmds.file(query=True, modified=True)
            )
            self.first._start_runtime_capture()
            self.first._runtime_timer.stop()
            self.first._start_runtime_capture()
            QtWidgets.QApplication.processEvents()
            self.checks["运行时取消交互"] = {
                "通过": bool(
                    self.first._runtime_capture.cancelling
                    and not self.first.runtime_button.isEnabled()
                    and self.first.runtime_button.text() == "正在取消…"
                    and not self.first.capture_button.isEnabled()
                    and not self.first.clinic_array.isEnabled()
                ),
                "控制器正在取消": self.first._runtime_capture.cancelling,
                "取消按钮已锁定": not self.first.runtime_button.isEnabled(),
                "按钮文案": self.first.runtime_button.text(),
                "捕获入口已锁定": not self.first.capture_button.isEnabled(),
                "诊所入口已锁定": not self.first.clinic_array.isEnabled(),
            }

        def verify_runtime_cancel(self):
            self.first._advance_runtime_capture()
            QtWidgets.QApplication.processEvents()
            modified_after = bool(cmds.file(query=True, modified=True))
            self.checks["运行时取消恢复"] = {
                "通过": bool(
                    not self.first._runtime_capture.active
                    and self.first.runtime_button.isEnabled()
                    and self.first.runtime_button.text() == "运行时"
                    and self.first.capture_button.isEnabled()
                    and self.first.clinic_array.isEnabled()
                    and self.first._runtime_snapshot is self.runtime_before_cancel
                    and modified_after == self.runtime_modified_before_cancel
                ),
                "采集会话已释放": not self.first._runtime_capture.active,
                "运行时入口已恢复": self.first.runtime_button.isEnabled(),
                "捕获入口已恢复": self.first.capture_button.isEnabled(),
                "诊所入口已恢复": self.first.clinic_array.isEnabled(),
                "上次证据未被覆盖": self.first._runtime_snapshot is self.runtime_before_cancel,
                "Maya 修改状态未改变": modified_after == self.runtime_modified_before_cancel,
            }

        def prepare_project_gate_scenario(self):
            from MayaScope.examples.generate.project_gate_fixture import build_fixture
            from MayaScope.project_audit import verify_project_audit

            fixture = build_fixture(self.output.parent / "project-gate-fixture")
            payload = verify_project_audit(Path(fixture["bundle"]))
            modified_before = bool(cmds.file(query=True, modified=True))
            self.first._show_project_audit(payload)
            self.first.project_gate.select_scene(1)
            self.first._select_project_scene(1)
            QtWidgets.QApplication.processEvents()
            summary = payload["summary"]
            self.checks["真实项目门禁"] = {
                "通过": bool(
                    self.first.project_gate.isVisible()
                    and self.first.project_gate.verdict.text() == "发布已阻断"
                    and len(self.first.project_gate.canvas._scenes) == 3
                    and self.first.project_gate.canvas._selected == 1
                    and summary["passed_scene_count"] == 2
                    and summary["blocked_scene_count"] == 1
                    and bool(cmds.file(query=True, modified=True)) == modified_before
                ),
                "双层签名": payload["project_sha256"],
                "场景数": summary["scene_count"],
                "通过场景": summary["passed_scene_count"],
                "阻断场景": summary["blocked_scene_count"],
                "原子发现": summary["atomic_finding_count"],
                "聚焦阻断镜头": self.first.project_gate.canvas._selected == 1,
                "Maya 修改状态未改变": bool(cmds.file(query=True, modified=True)) == modified_before,
            }

        def after_second(self):
            self.checks["重复启动清理"].update(
                {
                    "可见工作区": len(self.visible_workspaces()),
                    "通过": len(self.visible_workspaces()) == 1,
                }
            )
            old = self.second
            self.third = self.launch.run("workspace", development=True)
            self.third.resize(*self.window_size)
            self.checks["开发热重载"] = {
                "旧窗口已隐藏": not old.isVisible(),
                "创建重载实例": self.third is not old,
            }
            self.wait_ready(self.third, self.after_reload)

        def after_reload(self):
            visible = self.visible_workspaces()
            self.checks["开发热重载"].update(
                {"可见工作区": len(visible), "通过": len(visible) == 1}
            )
            bridge = self.third._selection_bridge
            active_before = sum(
                timer.isActive() for timer in self.third.findChildren(QtCore.QTimer)
            )
            self.launch.close_all()
            active_after = sum(
                timer.isActive() for timer in self.third.findChildren(QtCore.QTimer)
            )
            self.checks["关闭与资源释放"] = {
                "关闭前活动计时器": active_before,
                "关闭后活动计时器": active_after,
                "选择回调已移除": not bool(bridge and bridge.active),
                "窗口已隐藏": not self.third.isVisible(),
                "通过": active_after == 0 and not bool(bridge and bridge.active),
            }
            self.later(self.after_close, 500)

        def after_close(self):
            from MayaScope.maya_integration import remove_menu

            menu_removed = remove_menu()
            self.checks["菜单卸载"] = {
                "已移除": menu_removed,
                "仍存在": bool(cmds.menu("MayaScopeMainMenu", exists=True)),
                "通过": menu_removed and not cmds.menu("MayaScopeMainMenu", exists=True),
            }
            self.checks["关闭与资源释放"]["残留可见工作区"] = len(
                self.visible_workspaces()
            )
            self.checks["关闭与资源释放"]["通过"] = bool(
                self.checks["关闭与资源释放"]["通过"]
                and not self.visible_workspaces()
            )
            passed = all(item.get("通过") for item in self.checks.values())
            payload = {
                "format": "mayascope.gui-lifecycle-worker",
                "schema_version": 1,
                "ok": passed,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "maya_version": str(cmds.about(version=True)),
                "maya_api": str(cmds.about(apiVersion=True)),
                "plugin_version": self.version,
                "package_root": self.package_root,
                "screenshot": str(self.screenshot),
                "scenario": self.scenario,
                "window_size": list(self.window_size),
                "duration_seconds": round(time.perf_counter() - self.started, 3),
                "checks": self.checks,
            }
            _atomic_json(self.output, payload)
            QtCore.QTimer.singleShot(250, lambda: cmds.quit(force=True))

        def finish_error(self, exc):
            payload = {
                "format": "mayascope.gui-lifecycle-worker",
                "schema_version": 1,
                "ok": False,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "error": "%s: %s" % (type(exc).__name__, exc),
                "traceback": traceback.format_exc(),
                "checks": self.checks,
            }
            try:
                _atomic_json(self.output, payload)
            finally:
                QtCore.QTimer.singleShot(250, lambda: cmds.quit(force=True))

    # Keep a Maya-owned reference until the host exits.
    global _PROBE
    _PROBE = Probe()
    QtCore.QTimer.singleShot(0, lambda: _PROBE.guard(_PROBE.start))


_PROBE = None


__all__ = ["schedule"]
