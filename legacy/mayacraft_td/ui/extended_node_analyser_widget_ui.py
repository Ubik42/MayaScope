# -*- coding: utf-8 -*-
from MayaCraft.compat.qt import QtWidgets, QtCore, QtGui
from MayaCraft.ui.collapsible_widget import CollapsibleWidget

# 假设 logic 中会有这些方法，这里先占位引用，实际运行时需要你的 logic 层配合
from MayaCraft.core.logic.td import extended_node_analyser_widget_logic as logic


# -----------------------------------------------------------------------------
# 1. Notion 风格绘制代理 (用于绘制圆角标签)
# -----------------------------------------------------------------------------
class TagDelegate(QtWidgets.QStyledItemDelegate):
    """
    在表格单元格中绘制圆角标签 (Pill shape)。
    支持单个标签 (Type) 或多个标签 (Sets)。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.padding = 4
        self.radius = 4

    def paint(self, painter, option, index):
        # 获取数据 (期望是字符串列表，或者逗号分隔的字符串)
        data = index.data(QtCore.Qt.DisplayRole)
        if not data:
            return

        # 获取背景色 (从 Model 中获取 DecorationRole，或者默认)
        bg_color = index.data(QtCore.Qt.BackgroundRole) or QtGui.QColor("#444444")
        text_color = QtGui.QColor("#FFFFFF")

        # 准备 Painter
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # 解析数据：如果是列表则直接用，如果是字符串则按逗号分割
        tags = data if isinstance(data, list) else str(data).split(",")
        tags = [t.strip() for t in tags if t.strip()]

        # 起始绘制位置
        x_offset = option.rect.x() + self.padding
        y_offset = option.rect.y() + self.padding
        row_height = option.rect.height() - (2 * self.padding)

        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)

        for tag_text in tags:
            # 计算文字宽度
            fm = QtGui.QFontMetrics(font)
            text_width = fm.horizontalAdvance(tag_text)
            rect_width = text_width + 16  # 左右留白

            # 绘制圆角矩形背景
            tag_rect = QtCore.QRectF(x_offset, y_offset, rect_width, row_height)

            # 只有当宽度不越界时才绘制
            if x_offset + rect_width < option.rect.right():
                path = QtGui.QPainterPath()
                path.addRoundedRect(tag_rect, self.radius, self.radius)

                painter.fillPath(path, bg_color)

                # 绘制文字
                painter.setPen(text_color)
                painter.drawText(tag_rect, QtCore.Qt.AlignCenter, tag_text)

                x_offset += rect_width + 6  # 下一个标签的间距
            else:
                break  # 空间不足，停止绘制

        painter.restore()


# -----------------------------------------------------------------------------
# 2. 颜色管理器弹窗
# -----------------------------------------------------------------------------
class ColorManagerDialog(QtWidgets.QDialog):
    """
    简单的颜色配置窗口：列出 Node Type，点击按钮修改颜色
    """

    colors_updated = QtCore.Signal(dict)  # 信号：颜色配置已更改

    def __init__(self, type_color_map, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Node Type Color Manager")
        self.resize(300, 400)
        self.type_color_map = type_color_map.copy()  # 本地副本

        layout = QtWidgets.QVBoxLayout(self)

        # 滚动区域
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll_widget = QtWidgets.QWidget()
        self.form_layout = QtWidgets.QFormLayout(self.scroll_widget)
        scroll.setWidget(self.scroll_widget)

        layout.addWidget(scroll)

        # 底部按钮
        btn_layout = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("保存并应用")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QtWidgets.QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self._populate_ui()

    def _populate_ui(self):
        # 清空布局
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 生成配置项
        for node_type, color_hex in self.type_color_map.items():
            btn = QtWidgets.QPushButton()
            btn.setStyleSheet(
                f"background-color: {color_hex}; border: none; height: 20px;"
            )
            btn.clicked.connect(lambda _, t=node_type, b=btn: self._pick_color(t, b))
            self.form_layout.addRow(node_type, btn)

    def _pick_color(self, node_type, btn):
        current_color = QtGui.QColor(self.type_color_map.get(node_type, "#555555"))
        color = QtWidgets.QColorDialog.getColor(current_color, self, "Select Color")
        if color.isValid():
            hex_color = color.name()
            self.type_color_map[node_type] = hex_color
            btn.setStyleSheet(
                f"background-color: {hex_color}; border: none; height: 20px;"
            )

    def _on_save(self):
        self.colors_updated.emit(self.type_color_map)
        self.accept()


# -----------------------------------------------------------------------------
# 3. 主 UI 组件
# -----------------------------------------------------------------------------
class ExtendedNodeAnalyserWidget(CollapsibleWidget):
    def __init__(self, parent=None):
        super().__init__("4. 场景类型viewer", parent)

        # 默认颜色配置 (示例) - 实际应存储在配置 json 中
        self.type_color_map = {
            "kPluginDependNode": "#FF6B6B",
            "kMesh": "#4ECDC4",
            "kTransform": "#FFE66D",
            "unknown": "#95A5A6",
        }

        # 数据缓存，用于前端过滤
        self.all_node_data = []

        layout = QtWidgets.QVBoxLayout()
        self._create_toolbar(layout)
        self._create_filters(layout)
        self._create_table(layout)
        self.set_content_layout(layout)

        self._connect_signals()

    def _create_toolbar(self, layout):
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)

        self.info_label = QtWidgets.QLabel("节点数据库")
        self.info_label.setStyleSheet("font-weight: bold; color: #AAAAAA;")

        self.analyse_btn = QtWidgets.QPushButton(" 分析场景 (Refresh)")
        self.analyse_btn.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload)
        )

        self.color_btn = QtWidgets.QPushButton(" 颜色配置")
        self.color_btn.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        )

        toolbar.addWidget(self.info_label)
        toolbar.addStretch()
        toolbar.addWidget(self.analyse_btn)
        toolbar.addWidget(self.color_btn)

        layout.addLayout(toolbar)

    def _create_filters(self, layout):
        """创建类似 Excel/Notion 的过滤器"""
        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.setSpacing(10)

        # 过滤器：节点类型
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.setPlaceholderText("Filter by Type...")
        self.type_combo.addItem("All Types")

        # 过滤器：所属集合
        self.set_combo = QtWidgets.QComboBox()
        self.set_combo.setPlaceholderText("Filter by Set...")
        self.set_combo.addItem("All Sets")

        filter_layout.addWidget(QtWidgets.QLabel("筛选:"))
        filter_layout.addWidget(self.type_combo, 1)
        filter_layout.addWidget(self.set_combo, 1)

        layout.addLayout(filter_layout)

    def _create_table(self, layout):
        self.node_table = QtWidgets.QTableWidget(0, 3)
        self.node_table.setHorizontalHeaderLabels(
            ["Node Name", "Node Type", "Belong to Sets"]
        )

        # 表格样式调整
        header = self.node_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)  # Type 列自适应
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)  # Sets 列自适应
        header.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        self.node_table.verticalHeader().setVisible(False)  # 隐藏行号
        self.node_table.setAlternatingRowColors(False)  # 关闭默认交替，我们要自己上色
        self.node_table.setShowGrid(False)  # Notion 风格通常没有强烈网格
        self.node_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.node_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #333;
                background-color: #2b2b2b;
                gridline-color: #333;
            }
            QHeaderView::section {
                background-color: #333;
                padding: 4px;
                border: none;
                font-weight: bold;
            }
        """)

        # 设置自定义代理来绘制 "Type" 和 "Sets" 列的标签
        self.tag_delegate = TagDelegate(self.node_table)
        self.node_table.setItemDelegateForColumn(1, self.tag_delegate)
        self.node_table.setItemDelegateForColumn(2, self.tag_delegate)

        layout.addWidget(self.node_table)

    def _connect_signals(self):
        self.analyse_btn.clicked.connect(self._on_analyse)
        self.color_btn.clicked.connect(self._open_color_manager)
        self.type_combo.currentIndexChanged.connect(self._filter_table)
        self.set_combo.currentIndexChanged.connect(self._filter_table)

    def _on_analyse(self):
        self.node_table.setRowCount(0)
        # 修改这里：调用新的函数
        self.all_node_data = logic.get_scene_nodes_info()

        # 下面保持不变
        print(f"分析完成，共找到 {len(self.all_node_data)} 个节点")
        self._update_filter_options()
        self._populate_table(self.all_node_data)
        self._sync_colors_with_data()

    def _populate_table(self, data_list):
        """将数据填入表格"""
        self.node_table.setRowCount(0)
        self.node_table.setRowCount(len(data_list))

        for row, info in enumerate(data_list):
            node_name = info.get("name", "N/A")
            node_type = info.get("type", "unknown")
            node_sets = info.get("sets", [])  # List or String

            # --- Column 0: Name ---
            item_name = QtWidgets.QTableWidgetItem(node_name)
            self.node_table.setItem(row, 0, item_name)

            # 获取该类型的对应颜色
            type_color_hex = self.type_color_map.get(node_type, "#555555")
            c = QtGui.QColor(type_color_hex)

            # --- 需求：每一行根据 node type 上色 ---
            # 方案A：整个背景上色（透明度低一点以免无法阅读）
            row_bg_color = QtGui.QColor(type_color_hex)
            row_bg_color.setAlpha(40)  # 设置很高的透明度，只是淡淡的背景

            # 给第一列设置行背景色
            item_name.setBackground(row_bg_color)

            # --- Column 1: Type (Tag Style) ---
            item_type = QtWidgets.QTableWidgetItem(node_type)
            # TagDelegate 会读取 BackgroundRole 来画胶囊背景
            item_type.setBackground(c)
            self.node_table.setItem(row, 1, item_type)

            # --- Column 2: Sets (Tag Style) ---
            sets_str = (
                ",".join(node_sets) if isinstance(node_sets, list) else str(node_sets)
            )
            item_sets = QtWidgets.QTableWidgetItem(sets_str)
            # Sets 可以用灰色或者统一颜色，也可以跟 Type 一样
            item_sets.setBackground(QtGui.QColor("#555555"))
            self.node_table.setItem(row, 2, item_sets)

    def _update_filter_options(self):
        """根据当前数据更新下拉框"""
        all_types = set()
        all_sets = set()

        for info in self.all_node_data:
            all_types.add(info.get("type", "unknown"))
            sets = info.get("sets", [])
            if isinstance(sets, list):
                all_sets.update(sets)
            else:
                all_sets.add(str(sets))

        # 保持 "All Types" 在第一个
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItem("All Types")
        self.type_combo.addItems(sorted(list(all_types)))
        self.type_combo.blockSignals(False)

        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        self.set_combo.addItem("All Sets")
        self.set_combo.addItems(sorted(list(all_sets)))
        self.set_combo.blockSignals(False)

    def _filter_table(self):
        """前端过滤逻辑"""
        target_type = self.type_combo.currentText()
        target_set = self.set_combo.currentText()

        filtered_data = []
        for info in self.all_node_data:
            # Type 检查
            type_match = (target_type == "All Types") or (
                info.get("type") == target_type
            )

            # Set 检查
            current_sets = info.get("sets", [])
            set_match = False
            if target_set == "All Sets":
                set_match = True
            else:
                # 检查 target_set 是否在当前节点的集合列表中
                set_match = target_set in current_sets

            if type_match and set_match:
                filtered_data.append(info)

        self._populate_table(filtered_data)

    def _sync_colors_with_data(self):
        """如果发现新的类型没有颜色配置，给它随机分配一个或默认颜色"""
        existing_types = self.type_color_map.keys()
        for info in self.all_node_data:
            nt = info.get("type")
            if nt and nt not in existing_types:
                # 分配默认灰或者随机颜色
                self.type_color_map[nt] = "#666666"

    def _open_color_manager(self):
        """打开颜色管理器"""
        dialog = ColorManagerDialog(self.type_color_map, self)
        dialog.colors_updated.connect(self._on_colors_updated)
        dialog.exec()

    def _on_colors_updated(self, new_map):
        """颜色更新后的回调"""
        self.type_color_map = new_map
        # 重新刷新表格以应用新颜色
        # 如果当前有过滤，应该重绘当前过滤后的数据
        self._filter_table()
