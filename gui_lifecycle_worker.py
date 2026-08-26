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
            self.deadline = self.started + 45.0
            self.output = Path(os.environ["MAYASCOPE_GUI_LIFECYCLE_WORKER"])
            self.screenshot = Path(os.environ["MAYASCOPE_GUI_LIFECYCLE_SCREENSHOT"])
            self.checks = {}
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
                and not (window._clinic_thread and window._clinic_thread.isRunning())
            )

        def wait_ready(self, window, callback):
            if self.ready(window):
                callback()
            else:
                self.later(lambda: self.wait_ready(window, callback), 150)

        def start(self):
            from MayaScope import __version__, launch

            self.launch = launch
            self.version = __version__
            self.first = launch.run("workspace")
            self.first.resize(1480, 900)
            self.wait_ready(self.first, self.after_first)

        def after_first(self):
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
            old = self.first
            self.second = self.launch.run("workspace")
            self.second.resize(1480, 900)
            self.checks["重复启动清理"] = {
                "旧窗口已隐藏": not old.isVisible(),
                "创建新实例": self.second is not old,
            }
            self.wait_ready(self.second, self.after_second)

        def after_second(self):
            self.checks["重复启动清理"].update(
                {
                    "可见工作区": len(self.visible_workspaces()),
                    "通过": len(self.visible_workspaces()) == 1,
                }
            )
            old = self.second
            self.third = self.launch.run("workspace", development=True)
            self.third.resize(1480, 900)
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
                "screenshot": str(self.screenshot),
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
