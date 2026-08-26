# -*- coding: utf-8 -*-
import maya.cmds as cmds
from MayaCraft.compat.qt import QtWidgets, QtCore
from MayaCraft.ui.collapsible_widget import CollapsibleWidget


class NodeViewerWidget(CollapsibleWidget):
    def __init__(self, parent=None):
        super().__init__("1. 节点查看器 | Node Viewer", parent)
        layout = QtWidgets.QVBoxLayout()
        self._create_content(layout)
        self.set_content_layout(layout)

    def _create_content(self, layout):
        # 定义内部样式
        self.setStyleSheet("""
            QPushButton { 
                background-color: #5285a6; color: white; border-radius: 4px; padding: 6px; font-size: 12px; 
            }
            QPushButton:hover { background-color: #639ubc; }
            QPushButton:pressed { background-color: #406882; }
        """)

        # 1. Isolate
        btn_iso = QtWidgets.QPushButton("Isolate Selected (Reset Graph)")
        btn_iso.clicked.connect(self.on_isolate_clicked)
        btn_iso.setStyleSheet(
            "background-color: #d65d5d; font-weight: bold; color: white; padding: 8px;"
        )
        btn_iso.setToolTip("清空 Node Editor 并仅显示当前选择的节点")

        # 2. Add Inputs/Outputs
        lyt_add = QtWidgets.QHBoxLayout()
        btn_add_in = QtWidgets.QPushButton("Add Inputs (<)")
        btn_add_in.clicked.connect(lambda: self.on_expand_graph(True, False))
        btn_add_out = QtWidgets.QPushButton("Add Outputs (>)")
        btn_add_out.clicked.connect(lambda: self.on_expand_graph(False, True))
        lyt_add.addWidget(btn_add_in)
        lyt_add.addWidget(btn_add_out)

        # 3. Remove Inputs/Outputs
        lyt_rem = QtWidgets.QHBoxLayout()
        btn_rem_in = QtWidgets.QPushButton("Remove Inputs (<)")
        btn_rem_in.clicked.connect(lambda: self.on_reduce_graph(True, False))
        btn_rem_out = QtWidgets.QPushButton("Remove Outputs (>)")
        btn_rem_out.clicked.connect(lambda: self.on_reduce_graph(False, True))
        lyt_rem.addWidget(btn_rem_in)
        lyt_rem.addWidget(btn_rem_out)

        # 4. Clear ObjectSets
        btn_cls = QtWidgets.QPushButton("Remove All 'objectSet' Nodes")
        btn_cls.clicked.connect(self.on_remove_object_sets)
        btn_cls.setStyleSheet("background-color: #7d5e28; color: white;")
        btn_cls.setToolTip("从当前图表中移除所有 objectSet 类型节点")

        layout.addWidget(btn_iso)
        layout.addLayout(lyt_add)
        layout.addLayout(lyt_rem)
        layout.addWidget(btn_cls)

    # --- Logic ---

    def get_ne(self):
        """获取当前活动的 Node Editor 面板"""
        pnls = cmds.getPanel(scriptType="nodeEditorPanel")
        if not pnls:
            return None
        for p in pnls:
            if cmds.control(p, ex=1) and cmds.control(p, q=1, vis=1):
                return p
        return pnls[0] if pnls else None

    def on_expand_graph(self, up, down):
        """添加节点逻辑，已增加 objectSet 过滤"""
        sel = cmds.ls(sl=1)
        pnl = self.get_ne()
        if sel and pnl:
            try:
                # 1. 获取所有连接的节点
                raw_conns = cmds.listConnections(sel, s=up, d=down) or []

                # 2. 过滤掉 objectSet 类型的节点
                # (注意：listConnections 有时返回短名有时长名，nodeType 对两者都有效)
                filtered_conns = [
                    n for n in raw_conns if cmds.nodeType(n) != "objectSet"
                ]

                if filtered_conns:
                    # 3. 添加过滤后的节点并整理布局
                    cmds.nodeEditor(
                        pnl + "NodeEditorEd", e=1, addNode=filtered_conns, layout=1
                    )
            except Exception as e:
                print(f"Error expanding graph: {e}")

    def on_reduce_graph(self, up, down):
        sel = cmds.ls(sl=1)
        pnl = self.get_ne()
        if sel and pnl:
            rem = cmds.listConnections(sel, s=up, d=down) or []
            # 仅移除未选中的连接节点，保留当前选择
            rem = [n for n in rem if n not in sel]
            if rem:
                cmds.nodeEditor(pnl + "NodeEditorEd", e=1, removeNode=rem)

    def on_remove_object_sets(self):
        pnl = self.get_ne()
        if pnl:
            try:
                cmds.nodeEditor(
                    pnl + "NodeEditorEd",
                    e=1,
                    removeNode=cmds.ls(type="objectSet") or [],
                )
            except Exception:
                pass

    def on_isolate_clicked(self):
        sel = cmds.ls(sl=1)
        pnl = self.get_ne()
        if sel and pnl:
            ed = pnl + "NodeEditorEd"
            try:
                # 清空并添加选择
                cmds.nodeEditor(ed, e=1, rootNode="", addNode=sel)
                # 隐藏 Shape 节点以保持图表整洁
                shapes = cmds.listRelatives(sel, shapes=1, f=1) or []
                hide = [s for s in shapes if s not in cmds.ls(sel, l=1)]
                if hide:
                    cmds.nodeEditor(ed, e=1, removeNode=hide)
                cmds.nodeEditor(ed, e=1, layout=1, frameAll=1)
            except Exception:
                pass
