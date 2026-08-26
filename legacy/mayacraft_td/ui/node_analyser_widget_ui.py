# -*- coding: utf-8 -*-
import maya.cmds as cmds
from MayaCraft.compat.qt import QtWidgets

try:
    from auroraview import QtWebView
except ImportError:
    QtWebView = None
    print("AuroraView not found. Web Render will be disabled.")
from MayaCraft.ui.collapsible_widget import CollapsibleWidget
from MayaCraft.core.logic.td.node_analyser_logic import NodeAnalyserLogic


# =========================================================================
# Main Widget
# =========================================================================
class NodeAnalyserWidget(CollapsibleWidget):
    def __init__(self, parent=None):
        super().__init__("2. 节点分析器 | Node Analyser", parent)
        self.logic = NodeAnalyserLogic()

        layout = QtWidgets.QVBoxLayout()
        self._create_content(layout)
        self.set_content_layout(layout)

        # Keep reference to the window to prevent GC
        self.web_view_window = None

    def _create_content(self, layout):
        # Options
        opt_layout = QtWidgets.QHBoxLayout()
        self.chk_smart = QtWidgets.QCheckBox("🌀 智能追踪")
        self.chk_smart.setChecked(True)
        self.chk_in = QtWidgets.QCheckBox("Inputs")
        self.chk_in.setChecked(False)
        self.chk_out = QtWidgets.QCheckBox("Outputs")
        self.chk_out.setChecked(True)
        opt_layout.addWidget(self.chk_smart)
        opt_layout.addWidget(self.chk_in)
        opt_layout.addWidget(self.chk_out)
        opt_layout.addStretch()
        layout.addLayout(opt_layout)

        # Tabs
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #444; background-color: #1e1e1e; }
            QTabBar::tab { background: #333; color: #aaa; padding: 5px 10px; }
            QTabBar::tab:selected { background: #444; color: white; border-bottom: 2px solid #5285a6; }
        """)

        self.txt_md = QtWidgets.QTextEdit()
        self.txt_md.setReadOnly(True)
        self.txt_md.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas; font-size: 11px;"
        )

        self.txt_mm = QtWidgets.QTextEdit()
        self.txt_mm.setReadOnly(True)
        self.txt_mm.setStyleSheet(
            "background-color: #1e1e1e; color: #aaddff; font-family: Consolas; font-size: 11px;"
        )

        self.tabs.addTab(self.txt_md, "📝 Markdown")
        self.tabs.addTab(self.txt_mm, "💻 Mermaid")
        self.tabs.setCurrentIndex(0)
        self.tabs.setMinimumHeight(300)
        layout.addWidget(self.tabs)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_gen = QtWidgets.QPushButton("🚀 开始分析 (Generate)")
        self.btn_gen.setStyleSheet(
            "background-color: #5285a6; color: white; padding: 6px; font-weight: bold;"
        )
        self.btn_export = QtWidgets.QPushButton("📋 复制/截图 (Export)")
        self.btn_export.setStyleSheet(
            "background-color: #444; color: white; padding: 6px;"
        )

        self.btn_web = QtWidgets.QPushButton("🌐 Web Render")
        self.btn_web.setStyleSheet(
            "background-color: #e67e22; color: white; padding: 6px; font-weight: bold;"
        )

        btn_layout.addWidget(self.btn_gen)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_web)
        layout.addLayout(btn_layout)

        self.btn_gen.clicked.connect(self._on_generate)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_web.clicked.connect(self._on_web_render)

    def _on_generate(self):
        sel = cmds.ls(sl=1, long=True)
        if not sel:
            self.txt_md.setText("Select nodes first.")
            return

        # 1. 基础数据准备
        nodes = self.logic.get_expanded_selection(
            sel, smart_trace=self.chk_smart.isChecked()
        )

        # 2. 获取当前 Tab 索引
        current_idx = self.tabs.currentIndex()

        # 3. 按需生成
        if current_idx == 0:
            md_text = self.logic.generate_markdown(nodes, self.chk_smart.isChecked())
            self.txt_md.setText(md_text)
            print("Generated Markdown only.")

        elif current_idx == 1:
            mm_text = self.logic.generate_mermaid(
                nodes, self.chk_in.isChecked(), self.chk_out.isChecked()
            )
            self.txt_mm.setText(mm_text)
            print("Generated Mermaid Text only.")

    def _on_export(self):
        idx = self.tabs.currentIndex()
        cb = QtWidgets.QApplication.clipboard()
        msg = ""

        if idx == 0:
            cb.setText(self.txt_md.toPlainText())
            msg = "Markdown Copied"
        elif idx == 1:
            cb.setText(self.txt_mm.toPlainText())
            msg = "Mermaid Code Copied"

        if msg:
            cmds.inViewMessage(
                amg=f'<span style="color: #00FF00;">{msg}</span>',
                pos="midCenter",
                fade=True,
            )

    def _on_web_render(self):
        """
        Generate Mermaid text and render it using AuroraView (QtWebView).
        """
        if QtWebView is None:
            cmds.warning("AuroraView module is not installed. Cannot render.")
            return

        sel = cmds.ls(sl=1, long=True)
        if not sel:
            self.txt_md.setText("Select nodes first.")
            return

        # 1. 基础数据准备
        nodes = self.logic.get_expanded_selection(
            sel, smart_trace=self.chk_smart.isChecked()
        )

        # 2. 生成 Mermaid 代码
        mm_text = self.logic.generate_mermaid(
            nodes, self.chk_in.isChecked(), self.chk_out.isChecked()
        )
        self.txt_mm.setText(mm_text)

        # 3. 生成 HTML
        html_content = self.logic.generate_mermaid_html(mm_text)

        # 4. AuroraView 渲染
        try:
            # 如果窗口已存在，先关闭 (或者重用，这里选择重建以保持状态清洁)
            if self.web_view_window:
                self.web_view_window.close()
                self.web_view_window.deleteLater()

            # 创建独立的 Dialog 窗口
            self.web_view_window = QtWidgets.QDialog(self)
            self.web_view_window.setWindowTitle("Mermaid Graph (AuroraView)")
            self.web_view_window.resize(1000, 800)

            # 布局
            dlg_layout = QtWidgets.QVBoxLayout(self.web_view_window)
            dlg_layout.setContentsMargins(0, 0, 0, 0)

            # 创建 WebView
            # 注意: 可以在这里启用 dev_tools=True 方便调试
            self.webview = QtWebView(self.web_view_window, dev_tools=False)
            dlg_layout.addWidget(self.webview)

            # 加载 HTML
            self.webview.load_html(html_content)

            # 显示
            self.web_view_window.show()
            print("Opened Graph in AuroraView.")

        except Exception as e:
            cmds.warning(f"AuroraView Render Failed: {e}")
            import traceback

            traceback.print_exc()
