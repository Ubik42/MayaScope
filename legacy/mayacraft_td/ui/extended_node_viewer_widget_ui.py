# -*- coding: utf-8 -*-
from MayaCraft.compat.qt import QtWidgets, QtCore, QtGui
from MayaCraft.core.logic.td import extended_node_viewer_widget_logic as logic
from MayaCraft.ui.collapsible_widget import CollapsibleWidget


class ExtendedNodeViewerWidget(CollapsibleWidget):
    def __init__(self, parent=None):
        super().__init__("3. 单体节点Viewer", parent)
        layout = QtWidgets.QVBoxLayout()
        self._create_content(layout)
        self.set_content_layout(layout)
        self._connect_signals()

        # 初始化时尝试刷新一次
        self._on_refresh_view()

    def _create_content(self, layout):
        # 0. 当前选中节点提示
        self.current_node_lbl = QtWidgets.QLabel("当前未选中节点")
        self.current_node_lbl.setStyleSheet("color: #aaa; font-style: italic;")
        self.refresh_btn = QtWidgets.QPushButton("刷新选中")

        top_bar = QtWidgets.QHBoxLayout()
        top_bar.addWidget(self.current_node_lbl)
        top_bar.addWidget(self.refresh_btn)

        # 1. 节点过滤设置
        filter_layout = QtWidgets.QHBoxLayout()
        self.connected_only_cb = QtWidgets.QCheckBox("仅显示连接")
        self.has_value_cb = QtWidgets.QCheckBox("仅显示非默认值")
        self.connected_only_cb.setChecked(False)  # 默认全显示方便调试
        self.has_value_cb.setChecked(False)

        filter_layout.addWidget(self.connected_only_cb)
        filter_layout.addWidget(self.has_value_cb)

        # 2. 属性展示列表
        self.attr_tree = QtWidgets.QTreeWidget()
        self.attr_tree.setHeaderLabels(["属性名", "当前值", "连接源/目标"])
        self.attr_tree.setAlternatingRowColors(True)
        # 调整列宽
        self.attr_tree.setColumnWidth(0, 150)
        self.attr_tree.setColumnWidth(1, 80)

        # 3. 自定义过滤并添加至 Node Editor
        group_box = QtWidgets.QGroupBox("Node Editor 助手")
        add_layout = QtWidgets.QVBoxLayout()

        input_layout = QtWidgets.QHBoxLayout()
        self.type_filter_edit = QtWidgets.QLineEdit()
        self.type_filter_edit.setPlaceholderText(
            "节点类型 (如: lambert, skinCluster)..."
        )
        self.add_to_editor_btn = QtWidgets.QPushButton("添加至当前编辑器")
        input_layout.addWidget(self.type_filter_edit)
        input_layout.addWidget(self.add_to_editor_btn)

        add_layout.addLayout(input_layout)
        group_box.setLayout(add_layout)

        layout.addLayout(top_bar)
        layout.addLayout(filter_layout)
        layout.addWidget(self.attr_tree)
        layout.addWidget(group_box)

    def _connect_signals(self):
        self.refresh_btn.clicked.connect(self._on_refresh_view)
        self.add_to_editor_btn.clicked.connect(self._on_add_to_editor)
        self.connected_only_cb.stateChanged.connect(self._on_refresh_view)
        self.has_value_cb.stateChanged.connect(self._on_refresh_view)

    def _on_refresh_view(self):
        """刷新属性视图"""
        # 1. 获取数据
        result = logic.get_filtered_attributes(
            self.connected_only_cb.isChecked(), self.has_value_cb.isChecked()
        )

        # 2. 更新 UI 状态
        node_name = result.get("node", None)
        if not node_name:
            self.current_node_lbl.setText("当前未选中节点")
            self.attr_tree.clear()
            return

        self.current_node_lbl.setText(f"当前节点: {node_name} ({result.get('type')})")

        # 3. 填充 TreeWidget
        self.attr_tree.clear()
        attrs_data = result.get("attributes", [])

        items = []
        for attr_info in attrs_data:
            # attr_info: {'name': 'tx', 'value': 1.0, 'connection': 'pCube1.tx', 'is_connected': True}
            item = QtWidgets.QTreeWidgetItem()
            item.setText(0, attr_info["name"])
            item.setText(1, str(attr_info["value"]))
            item.setText(2, attr_info["connection"])

            # 简单的颜色区分
            if attr_info["is_connected"]:
                item.setForeground(0, QtGui.QColor("#82cfff"))  # 蓝色表示连接
                item.setForeground(2, QtGui.QColor("#82cfff"))
            elif attr_info["is_non_default"]:
                item.setForeground(1, QtGui.QColor("#ffeb3b"))  # 黄色表示数值被修改过

            items.append(item)

        self.attr_tree.addTopLevelItems(items)

    def _on_add_to_editor(self):
        filter_text = self.type_filter_edit.text()
        if not filter_text:
            print("请输入节点类型")
            return

        count = logic.add_nodes_to_editor(filter_text)
        print(f"UI反馈: 已尝试添加 {count} 个 [{filter_text}] 类型的节点")
