# -*- coding: utf-8 -*-
from html import escape

import maya.cmds as cmds
import maya.mel as mel
from MayaScope.qt_compat import QtWidgets, QtCore, QtGui


# --- Maya 2025 兼容窗口获取 ---
def get_maya_window():
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == "MayaWindow":
            return widget
    return None


class SetManagerTool(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Manager Pro")
        self.resize(500, 600)  # 稍微调宽一点
        self.setWindowFlags(QtCore.Qt.Window)

        self.script_job_id = None

        self.init_ui()
        self.create_script_job()
        self.update_set_info()

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(15)

        # --- 1. 创建单个 Set ---
        group_single = QtWidgets.QGroupBox("1. Create Single Set")
        layout_single = QtWidgets.QHBoxLayout(group_single)
        self.le_single_name = QtWidgets.QLineEdit()
        self.le_single_name.setPlaceholderText("Set Name...")
        btn_single = QtWidgets.QPushButton("Create")
        btn_single.clicked.connect(self.on_create_single_set)
        layout_single.addWidget(self.le_single_name)
        layout_single.addWidget(btn_single)
        main_layout.addWidget(group_single)

        # --- 2. 按类型创建 ---
        group_type = QtWidgets.QGroupBox("2. Create Sets by Type")
        layout_type = QtWidgets.QHBoxLayout(group_type)
        self.le_type_prefix = QtWidgets.QLineEdit()
        self.le_type_prefix.setPlaceholderText("Prefix...")
        btn_type = QtWidgets.QPushButton("Create by Type")
        btn_type.clicked.connect(self.on_create_type_sets)
        layout_type.addWidget(self.le_type_prefix)
        layout_type.addWidget(btn_type)
        main_layout.addWidget(group_type)

        # --- 3. 信息展示 (核心修改) ---
        group_info = QtWidgets.QGroupBox("3. Object Sets Inspector")
        layout_info = QtWidgets.QVBoxLayout(group_info)

        self.text_info = QtWidgets.QTextEdit()
        self.text_info.setReadOnly(True)

        # 样式设置：
        # 1. 不换行 (NoWrap) -> 出现水平滚动条
        # 2. 字体加大
        # 3. 背景深色
        self.text_info.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.text_info.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Segoe UI', sans-serif; 
                font-size: 14pt; 
                background-color: #222222; 
                color: #eeeeee;
                border: 1px solid #444;
            }
        """)

        layout_info.addWidget(self.text_info)
        main_layout.addWidget(group_info)

        # 状态栏
        self.status_bar = QtWidgets.QLabel("Ready")
        self.status_bar.setStyleSheet("color: #888; font-size: 10pt;")
        main_layout.addWidget(self.status_bar)

    # =========================================================================
    # 颜色获取逻辑 (新增)
    # =========================================================================
    def get_set_color_hex(self, set_node):
        """
        获取 Maya Set 节点的 Drawing Overrides 颜色，并转为 Hex 字符串 (#RRGGBB)
        """
        if not cmds.objExists(set_node):
            return "#999999"  # 默认灰

        # 检查是否启用了覆盖
        try:
            enable = cmds.getAttr(f"{set_node}.overrideEnabled")
            if not enable:
                return "#CCCCCC"  # 未启用覆盖，显示为亮白/灰色

            # 检查是 RGB 模式 还是 Index 模式
            rgb_mode = cmds.getAttr(f"{set_node}.overrideRGBColors")

            if rgb_mode:
                # RGB 模式 (Maya 2016+)
                raw_rgb = cmds.getAttr(f"{set_node}.overrideColorRGB")[0]  # returns (r,g,b)
                # 转换 float 0-1 到 int 0-255 并转 hex
                r = int(raw_rgb[0] * 255)
                g = int(raw_rgb[1] * 255)
                b = int(raw_rgb[2] * 255)
                return f"#{r:02x}{g:02x}{b:02x}"
            else:
                # Index 模式 (0-31)
                idx = cmds.getAttr(f"{set_node}.overrideColor")
                # 获取该索引对应的 RGB 值
                # cmds.colorIndex 返回的是 [r, g, b] (0-1 float)
                if idx > 0:
                    raw_rgb = cmds.colorIndex(idx, q=True)
                    r = int(raw_rgb[0] * 255)
                    g = int(raw_rgb[1] * 255)
                    b = int(raw_rgb[2] * 255)
                    return f"#{r:02x}{g:02x}{b:02x}"
                else:
                    return "#CCCCCC"  # 索引0通常是默认黑/灰
        except (RuntimeError, TypeError, ValueError):
            return "#CCCCCC"

    # =========================================================================
    # 功能逻辑
    # =========================================================================

    def on_create_single_set(self):
        sel = cmds.ls(sl=True)
        name = self.le_single_name.text().strip()
        if not sel or not name:
            self.status_bar.setText("Select objects and enter a name.")
            return
        try:
            new_set = cmds.sets(sel, name=name)
            self.status_bar.setText(f"Created: {new_set}")
            self.update_set_info()
        except Exception as e:
            self.status_bar.setText(str(e))

    def on_create_type_sets(self):
        sel = cmds.ls(sl=True)
        prefix = self.le_type_prefix.text().strip() or "Auto"
        if not sel:
            self.status_bar.setText("Select one or more objects.")
            return

        type_map = {}
        for node in sel:
            t = cmds.nodeType(node)
            type_map.setdefault(t, []).append(node)

        created = []
        for t, nodes in type_map.items():
            s_name = f"{prefix}_{t}_set"
            created.append(cmds.sets(nodes, name=s_name))

        self.status_bar.setText(f"Created: {', '.join(created)}")
        self.update_set_info()

    def update_set_info(self):
        """刷新显示，使用 HTML 格式化颜色和布局"""
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return

        sel = cmds.ls(sl=True)
        if not sel:
            self.text_info.setHtml("<span style='color:#777;'><i>Nothing selected...</i></span>")
            self.status_bar.setText("Ready")
            return

        html_content = ""

        for node in sel:
            # 获取所属 sets
            sets_transform = cmds.listSets(object=node) or []
            sets_shape = []
            shapes = cmds.listRelatives(node, shapes=True)
            if shapes:
                for s in shapes:
                    res = cmds.listSets(object=s)
                    if res: sets_shape.extend(res)

            all_sets = sorted(list(set(sets_transform + sets_shape)))

            # --- 构建单行 HTML ---
            # 格式: ● ObjectName [Set1] [Set2] ...

            line_html = f"<div style='margin-bottom: 5px; white-space: pre;'>"
            line_html += f"<span style='color: #eee; font-weight:bold;'>{escape(node)}</span>"

            if all_sets:
                line_html += " <span style='color:#666;'>&rarr;</span> "  # 箭头
                for s in all_sets:
                    # 获取该 Set 的颜色
                    color_hex = self.get_set_color_hex(s)

                    # 样式: 带有颜色的粗体文字，加一点方框背景感觉
                    # 如果背景太亮，也许字体需要阴影，这里简化为改变文字颜色
                    line_html += f"&nbsp;<span style='color:{color_hex}; font-weight:bold; background-color:#333; padding:2px 6px; border-radius:4px;'>{escape(s)}</span>"
            else:
                line_html += " <span style='color:#555;'><i>(No Sets)</i></span>"

            line_html += "</div>"
            html_content += line_html

        self.text_info.setHtml(html_content)
        self.status_bar.setText(f"Inspecting {len(sel)} objects")

    # =========================================================================
    # 生命周期
    # =========================================================================
    def create_script_job(self):
        if self.script_job_id is None:
            self.script_job_id = cmds.scriptJob(
                event=["SelectionChanged", self.update_set_info],
                protected=True
            )

    def closeEvent(self, event):
        if self.script_job_id is not None:
            if cmds.scriptJob(exists=self.script_job_id):
                cmds.scriptJob(kill=self.script_job_id, force=True)
            self.script_job_id = None
        super().closeEvent(event)


set_manager_ui = None


def close_tool():
    global set_manager_ui
    if set_manager_ui is None:
        return
    try:
        set_manager_ui.close()
        set_manager_ui.deleteLater()
    except RuntimeError:
        pass
    finally:
        set_manager_ui = None


def show_tool():
    global set_manager_ui
    close_tool()

    set_manager_ui = SetManagerTool(get_maya_window())
    set_manager_ui.show()
    return set_manager_ui


if __name__ == "__main__":
    show_tool()
