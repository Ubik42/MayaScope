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
    from PySide6 import QtCore, QtGui, QtWidgets
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
            if self.scenario == "atlas-scale":
                self.deadline = self.started + 100.0
            self.window_size = (
                int(os.environ.get("MAYASCOPE_GUI_LIFECYCLE_WIDTH", "1480")),
                int(os.environ.get("MAYASCOPE_GUI_LIFECYCLE_HEIGHT", "900")),
            )
            self.first = None
            self.second = None
            self.third = None

        def later(self, callback, milliseconds=250):
            QtCore.QTimer.singleShot(milliseconds, lambda: self.guard(callback))

        def mark_stage(self, name):
            if self.scenario == "atlas-scale":
                stage_check = self.checks.setdefault(
                    "大场景阶段", {"通过": True, "记录": []}
                )
                stage_check["记录"].append(
                    {
                        "阶段": name,
                        "累计秒": round(time.perf_counter() - self.started, 3),
                    }
                )

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
                and not window._scene_capture.active
                and window._clinic_thread is None
            )

        def wait_ready(self, window, callback):
            if self.scenario == "atlas-scale":
                dialogs = tuple(
                    widget
                    for widget in QtWidgets.QApplication.allWidgets()
                    if isinstance(widget, QtWidgets.QMessageBox) and widget.isVisible()
                )
                if dialogs:
                    messages = tuple(dialog.text() for dialog in dialogs)
                    for dialog in dialogs:
                        dialog.close()
                    raise RuntimeError(
                        "大场景首次捕获弹出错误：%s" % " | ".join(messages)
                    )
                session = getattr(window._scene_capture, "_session", None) if window else None
                progress = session.progress() if session is not None else None
                self.checks["大场景等待"] = {
                    "累计秒": round(time.perf_counter() - self.started, 3),
                    "窗口可见": bool(window and window.isVisible()),
                    "已有快照": bool(window and window._snapshot is not None),
                    "捕获进行中": bool(window and window._scene_capture.active),
                    "诊所进行中": bool(window and window._clinic_thread is not None),
                    "捕获阶段": progress.stage if progress else "",
                    "捕获完成项": progress.completed if progress else 0,
                    "捕获总项": progress.total if progress else 0,
                }
            if self.ready(window):
                callback()
            else:
                self.later(lambda: self.wait_ready(window, callback), 150)

        def start(self):
            import MayaScope
            from MayaScope import __version__, launch

            if self.scenario == "lens":
                from MayaScope.examples.generate.lens_chain_scene import build_scene

                self.lens_fixture = build_scene(
                    cmds, save_to=self.output.parent / "lens-chain-showcase.ma"
                )
            elif self.scenario == "atlas-scale":
                from MayaScope.examples.generate.atlas_scale_scene import build_scene

                self.mark_stage("开始生成夹具")
                self.atlas_scale_fixture = build_scene(
                    self.output.parent / "atlas-scale-showcase.ma"
                )
                self.mark_stage("夹具生成完成")
                cmds.file(
                    self.atlas_scale_fixture["scene"],
                    open=True,
                    force=True,
                    executeScriptNodes=False,
                    prompt=False,
                )
                cmds.currentTime(1.0, edit=True, update=False)
                cmds.file(save=True, force=True, type="mayaAscii")
                self.mark_stage("Maya 打开完成")

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
            self.mark_stage("工作区入口返回")
            self.first.resize(*self.window_size)
            self.wait_ready(self.first, self.after_first)

        def after_first(self):
            if self.scenario == "atlas-scale":
                self.checks["大场景等待"]["通过"] = True
            if self.scenario == "instruments":
                self.prepare_instrument_scenario()
            elif self.scenario == "runtime-cancel":
                self.prepare_runtime_cancel_scenario()
            elif self.scenario == "capture-cancel":
                self.prepare_capture_cancel_scenario()
            elif self.scenario == "project-gate":
                self.prepare_project_gate_scenario()
            elif self.scenario == "lens":
                self.prepare_lens_scenario()
            elif self.scenario == "atlas-scale":
                self.prepare_atlas_scale_scenario()
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
            if self.scenario == "atlas-scale":
                self.finish_atlas_scale()
                return
            if self.scenario == "instruments":
                self.verify_instrument_clear()
            elif self.scenario == "runtime-cancel":
                self.verify_runtime_cancel()
            elif self.scenario == "capture-cancel":
                self.verify_capture_cancel()
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

        def prepare_capture_cancel_scenario(self):
            self.capture_snapshot_before_cancel = self.first._snapshot
            self.capture_modified_before_cancel = bool(
                cmds.file(query=True, modified=True)
            )
            self.first.capture()
            self.first._capture_timer.stop()
            self.first.capture()
            QtWidgets.QApplication.processEvents()
            self.checks["场景捕获取消交互"] = {
                "通过": bool(
                    self.first._scene_capture.cancelling
                    and not self.first.capture_button.isEnabled()
                    and self.first.capture_button.text() == "正在取消…"
                    and not self.first.runtime_button.isEnabled()
                    and not self.first.bisect_button.isEnabled()
                    and not self.first.clinic_array.isEnabled()
                    and not self.first.pulse.isEnabled()
                ),
                "控制器正在取消": self.first._scene_capture.cancelling,
                "取消按钮已锁定": not self.first.capture_button.isEnabled(),
                "按钮文案": self.first.capture_button.text(),
                "运行时入口已锁定": not self.first.runtime_button.isEnabled(),
                "诊所入口已锁定": not self.first.clinic_array.isEnabled(),
                "性能入口已锁定": not self.first.pulse.isEnabled(),
            }

        def verify_capture_cancel(self):
            self.first._advance_capture()
            QtWidgets.QApplication.processEvents()
            modified_after = bool(cmds.file(query=True, modified=True))
            self.checks["场景捕获取消恢复"] = {
                "通过": bool(
                    not self.first._scene_capture.active
                    and self.first._snapshot is self.capture_snapshot_before_cancel
                    and self.first.capture_button.isEnabled()
                    and self.first.capture_button.text() == "捕获场景"
                    and self.first.runtime_button.isEnabled()
                    and self.first.bisect_button.isEnabled()
                    and self.first.clinic_array.isEnabled()
                    and self.first.pulse.isEnabled()
                    and modified_after == self.capture_modified_before_cancel
                ),
                "采集会话已释放": not self.first._scene_capture.active,
                "上次快照仍保留": self.first._snapshot is self.capture_snapshot_before_cancel,
                "捕获入口已恢复": self.first.capture_button.isEnabled(),
                "运行时入口已恢复": self.first.runtime_button.isEnabled(),
                "诊所入口已恢复": self.first.clinic_array.isEnabled(),
                "性能入口已恢复": self.first.pulse.isEnabled(),
                "Maya 修改状态未改变": modified_after == self.capture_modified_before_cancel,
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

        def prepare_lens_scenario(self):
            snapshot = self.first._snapshot
            focus = next(
                (node for node in snapshot.nodes if node.name == self.lens_fixture["focus"]),
                None,
            )
            if focus is None:
                raise RuntimeError("真实 Maya 快照没有收录根因透镜焦点")
            modified_before = bool(cmds.file(query=True, modified=True))
            self.first.lens_bar.set_direction("upstream")
            self.first.lens_bar.depth_spin.setValue(4)
            self.first._activate_focus(focus.id)
            QtWidgets.QApplication.processEvents()
            report = self.first._lens_report
            selected = self.first._selected_candidate
            expected_names = {"heroRoot", "globalMatrix", "spaceDecompose", "faceDriver"}
            candidate_names = {
                snapshot.node_map[candidate.node_id].name for candidate in report.candidates
            } if report else set()
            self.checks["真实根因透镜"] = {
                "通过": bool(
                    report
                    and report.direction == "upstream"
                    and len(report.candidates) >= 4
                    and expected_names.issubset(candidate_names)
                    and selected is not None
                    and self.first.lens_bar.isVisible()
                    and self.first.lens_ribbon.isVisible()
                    and self.first.lens_bar.focus_label.text() == self.lens_fixture["focus"]
                    and bool(cmds.file(query=True, modified=True)) == modified_before
                ),
                "焦点": self.first.lens_bar.focus_label.text(),
                "追踪方向": report.direction if report else "",
                "候选数": len(report.candidates) if report else 0,
                "候选节点": sorted(candidate_names),
                "已选候选": snapshot.node_map[selected.node_id].name if selected else "",
                "控制条可见": self.first.lens_bar.isVisible(),
                "证据带可见": self.first.lens_ribbon.isVisible(),
                "Maya 修改状态未改变": bool(cmds.file(query=True, modified=True)) == modified_before,
            }

        def prepare_atlas_scale_scenario(self):
            snapshot = self.first._snapshot
            atlas = self.first.atlas
            ranked = atlas._ranked_node_ids
            folded_id = next(
                (node_id for node_id in reversed(ranked) if node_id not in atlas._node_items),
                "",
            )
            transform_before = atlas.transform().m11()
            if folded_id:
                atlas.select_node_ids((folded_id,), center=False)
            image = QtGui.QImage(
                max(1, atlas.width()),
                max(1, atlas.height()),
                QtGui.QImage.Format.Format_ARGB32,
            )
            image.fill(QtGui.QColor("#07070F"))
            def render_once():
                painter = QtGui.QPainter(image)
                started = time.perf_counter()
                try:
                    atlas.render(painter)
                finally:
                    painter.end()
                return (time.perf_counter() - started) * 1000.0

            render_once()  # Font, path and style caches are cold on the first evidence frame.
            render_samples = tuple(render_once() for _index in range(3))
            render_ms = sorted(render_samples)[1]
            QtWidgets.QApplication.processEvents()
            stats = atlas.last_apply_stats
            self.checks["真实大场景语义窗"] = {
                "通过": bool(
                    len(snapshot.nodes) >= int(self.atlas_scale_fixture["nodes"])
                    and stats
                    and stats.visible_nodes <= 120
                    and stats.visible_edges <= 480
                    and stats.reused_nodes >= 119
                    and stats.camera_preserved
                    and folded_id in atlas._node_items
                    and stats.elapsed_ms < 100.0
                    and render_ms < 250.0
                ),
                "真实快照节点": len(snapshot.nodes),
                "真实快照连线": len(snapshot.edges),
                "物化节点": stats.visible_nodes if stats else -1,
                "物化连线": stats.visible_edges if stats else -1,
                "复用节点": stats.reused_nodes if stats else -1,
                "复用连线": stats.reused_edges if stats else -1,
                "内部换窗毫秒": round(stats.elapsed_ms, 3) if stats else -1,
                "同宿主生产视图换窗与栅格毫秒": round(render_ms, 3),
                "同宿主栅格样本毫秒": [round(value, 3) for value in render_samples],
                "折叠焦点已换入": folded_id in atlas._node_items,
                "视角保持": bool(
                    stats
                    and stats.camera_preserved
                    and abs(atlas.transform().m11() - transform_before) < 1e-9
                ),
                "素材 SHA-256": self.atlas_scale_fixture["sha256"],
                "Maya 修改状态": bool(cmds.file(query=True, modified=True)),
            }

        def finish_atlas_scale(self):
            bridge = self.first._selection_bridge
            active_before = sum(
                timer.isActive() for timer in self.first.findChildren(QtCore.QTimer)
            )
            self.launch.close_all()
            active_after = sum(
                timer.isActive() for timer in self.first.findChildren(QtCore.QTimer)
            )
            self.checks["关闭与资源释放"] = {
                "关闭前活动计时器": active_before,
                "关闭后活动计时器": active_after,
                "选择回调已移除": not bool(bridge and bridge.active),
                "窗口已隐藏": not self.first.isVisible(),
                "通过": active_after == 0 and not bool(bridge and bridge.active),
            }
            self.later(self.after_close, 500)

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
