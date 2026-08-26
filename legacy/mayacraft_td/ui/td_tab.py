# ui/td/td_tab.py
# -*- coding: utf-8 -*-
from MayaCraft.compat.qt import QtWidgets

# 导入 td 相关的子模块 UI
from MayaCraft.ui.td.node_viewer_widget_ui import NodeViewerWidget
from MayaCraft.ui.td.node_analyser_widget_ui import NodeAnalyserWidget
from MayaCraft.ui.td.extended_node_viewer_widget_ui import ExtendedNodeViewerWidget
from MayaCraft.ui.td.extended_node_analyser_widget_ui import ExtendedNodeAnalyserWidget


class TDTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._create_ui()

    def _create_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(5)

        # 滚动区域
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 5, 5, 5)
        content_layout.setSpacing(5)

        # --- 添加 td 功能模块 ---

        # 1. 节点查看器
        self.node_viewer_widget = NodeViewerWidget()
        content_layout.addWidget(self.node_viewer_widget)

        # 2. 节点分析器
        self.node_analyser_widget = NodeAnalyserWidget()
        content_layout.addWidget(self.node_analyser_widget)

        # 3. 扩展节点查看器
        self.extended_node_viewer_widget = ExtendedNodeViewerWidget()
        content_layout.addWidget(self.extended_node_viewer_widget)

        # 4. 扩展节点分析器
        self.extended_node_analyser_widget = ExtendedNodeAnalyserWidget()
        content_layout.addWidget(self.extended_node_analyser_widget)

        # 底部拉伸
        content_layout.addStretch()

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
