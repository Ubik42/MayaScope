# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.mel as mel
from MayaScope.qt_compat import QtWidgets, QtGui, QtCore


class MayaHierarchyInspectorExportMod(QtWidgets.QDialog):
    # 定义需要通过按钮一键控制的数学节点类型
    MATH_NODES = [
        "aimMatrix", "animCurveUU", "blendColors", "blendTwoAttr",
        "clamp", "composeMatrix", "decomposeMatrix", "multDoubleLinear",
        "distanceBetween", "multMatrix", "multiplyDivide"
    ]

    def __init__(self, parent=None):
        if not parent:
            parent = self.get_maya_window()
        super().__init__(parent)

        self.setWindowTitle("Hierarchy Inspector (Export Mod)")
        self.resize(1400, 800)
        self.setWindowFlags(QtCore.Qt.WindowType.Window)

        # 存储类型过滤菜单的 Action引用，以便代码控制
        self.type_actions = {}

        self.init_ui()
        self.refresh_tree()

    def get_maya_window(self):
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget.objectName() == "MayaWindow":
                return widget
        return None

    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --- Toolbar ---
        toolbar_layout = QtWidgets.QHBoxLayout()
        app_style = QtWidgets.QApplication.style()
        refresh_icon = app_style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload)

        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_refresh.setIcon(refresh_icon)
        self.btn_refresh.setFixedWidth(80)
        self.btn_refresh.clicked.connect(self.refresh_tree)

        self.btn_expand = QtWidgets.QPushButton("Expand")
        self.btn_expand.clicked.connect(self.expand_all)

        self.btn_collapse = QtWidgets.QPushButton("Collapse")
        self.btn_collapse.clicked.connect(self.collapse_all)

        # [NEW] Toggle Math Nodes Button
        self.btn_toggle_math = QtWidgets.QPushButton("Show Math Nodes")
        self.btn_toggle_math.setCheckable(True)
        self.btn_toggle_math.setToolTip("Toggle visibility of all utility/math nodes")
        self.btn_toggle_math.clicked.connect(self.toggle_math_nodes)

        # [NEW] Type Filter Menu Button
        self.btn_filter_types = QtWidgets.QToolButton()
        self.btn_filter_types.setText("Filter Types")
        self.btn_filter_types.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btn_filter_types.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)

        # Build the menu
        self.type_menu = QtWidgets.QMenu(self.btn_filter_types)
        self.build_type_filter_menu()
        self.btn_filter_types.setMenu(self.type_menu)

        # Search Bar
        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText("Search by Name...")
        self.search_bar.textChanged.connect(self.on_search_text_changed)

        toolbar_layout.addWidget(self.btn_refresh)
        toolbar_layout.addWidget(self.btn_expand)
        toolbar_layout.addWidget(self.btn_collapse)
        toolbar_layout.addWidget(self.btn_toggle_math)
        toolbar_layout.addWidget(self.btn_filter_types)
        toolbar_layout.addWidget(self.search_bar)

        # --- Tree Widget ---
        self.tree_widget = QtWidgets.QTreeWidget()
        self.tree_widget.setColumnCount(4)
        self.tree_widget.setHeaderLabels([
            "Name",
            "Type",
            "Locked Attrs",
            "Driven By / Input"
        ])

        self.tree_widget.setColumnWidth(0, 350)
        self.tree_widget.setColumnWidth(1, 100)
        self.tree_widget.setColumnWidth(2, 200)
        self.tree_widget.setColumnWidth(3, 500)

        self.tree_widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree_widget.setAlternatingRowColors(True)
        self.tree_widget.itemClicked.connect(self.on_item_clicked)

        # --- Bottom Buttons ---
        bottom_layout = QtWidgets.QHBoxLayout()

        # Export Option Checkbox
        self.chk_export_simple = QtWidgets.QCheckBox("Simple Export (Name & Type Only)")
        self.chk_export_simple.setToolTip(
            "Checked: Export Name + Type\nUnchecked: Export Name + Type + Locked + Driven")
        self.chk_export_simple.setChecked(True)  # Default Checked

        self.btn_copy_all = QtWidgets.QPushButton("Copy All (MD)")
        self.btn_copy_all.setMinimumHeight(40)
        self.btn_copy_all.clicked.connect(lambda: self.copy_to_md(only_selected=False))

        self.btn_copy_selected = QtWidgets.QPushButton("Copy Selected (MD)")
        self.btn_copy_selected.setMinimumHeight(40)
        self.btn_copy_selected.setStyleSheet(
            "background-color: #5285a6; color: white; font-weight: bold; border-radius: 4px;")
        self.btn_copy_selected.clicked.connect(lambda: self.copy_to_md(only_selected=True))

        bottom_layout.addWidget(self.chk_export_simple)
        bottom_layout.addWidget(self.btn_copy_all)
        bottom_layout.addWidget(self.btn_copy_selected)

        main_layout.addLayout(toolbar_layout)
        main_layout.addWidget(self.tree_widget)
        main_layout.addLayout(bottom_layout)

    # =========================================================================
    # Filter & Math Node Logic
    # =========================================================================

    def build_type_filter_menu(self):
        """构建类型筛选菜单"""
        self.type_actions = {}

        # 1. 默认的基础类型
        default_types = ["transform", "joint", "Constraints", "Others"]
        for t in default_types:
            action = QtGui.QAction(t, self.type_menu)
            action.setCheckable(True)
            action.setChecked(True)  # 默认选中
            action.triggered.connect(self.apply_filters)
            self.type_menu.addAction(action)
            self.type_actions[t] = action

        self.type_menu.addSeparator()

        # 2. 数学节点
        for math_node in self.MATH_NODES:
            action = QtGui.QAction(math_node, self.type_menu)
            action.setCheckable(True)
            action.setChecked(False)  # 数学节点默认不选中
            action.triggered.connect(self.apply_filters)
            self.type_menu.addAction(action)
            self.type_actions[math_node] = action

    def toggle_math_nodes(self):
        """按钮点击事件：全选或全不选数学节点"""
        should_check = self.btn_toggle_math.isChecked()
        self.btn_toggle_math.setText("Hide Math Nodes" if should_check else "Show Math Nodes")

        # 更新菜单里的勾选状态
        for node_type in self.MATH_NODES:
            if node_type in self.type_actions:
                self.type_actions[node_type].setChecked(should_check)

        # 应用过滤
        self.apply_filters()

    def on_search_text_changed(self, text):
        """搜索框文字改变时触发"""
        self.apply_filters()

    def apply_filters(self):
        """
        核心过滤逻辑：同时考虑 搜索文本 和 类型勾选
        """
        search_text = self.search_bar.text().lower()
        search_active = bool(search_text)

        # 获取当前允许显示的类型集合
        allowed_types = set()
        for type_name, action in self.type_actions.items():
            if action.isChecked():
                allowed_types.add(type_name)

        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree_widget)
        items_to_show = []

        while iterator.value():
            item = iterator.value()
            self.reset_item_visuals(item)  # 先重置颜色

            node_type = item.text(1)
            item_text = item.text(0).lower()

            # --- 1. 判断类型是否允许显示 ---
            type_allowed = False

            if "constraint" in node_type.lower():
                if "Constraints" in allowed_types:
                    type_allowed = True
            elif node_type in self.type_actions:
                # 如果节点类型直接在我们的列表中（如 joint, transform, 或具体的数学节点）
                if node_type in allowed_types:
                    type_allowed = True
            elif "Others" in allowed_types:
                # 如果不在我们的列表中，且勾选了 Others
                type_allowed = True

            # --- 2. 判断文本是否匹配 ---
            text_match = True
            if search_active:
                if search_text not in item_text:
                    text_match = False

            # --- 3. 综合判断 ---
            if type_allowed and text_match:
                if search_active:
                    # 搜索匹配高亮为红色
                    item.setForeground(0, QtGui.QColor("#ff4444"))
                    items_to_show.append(item)
                else:
                    item.setHidden(False)
            else:
                item.setHidden(True)

            iterator += 1

        # 搜索模式下，展开匹配项的父级
        if search_active:
            for item in items_to_show:
                self.show_item_and_parents(item)
        else:
            # 非搜索模式下，确保可见子项的父级是可见的
            iterator_vis = QtWidgets.QTreeWidgetItemIterator(self.tree_widget)
            while iterator_vis.value():
                item = iterator_vis.value()
                if not item.isHidden():
                    parent = item.parent()
                    while parent:
                        parent.setHidden(False)
                        parent = parent.parent()
                iterator_vis += 1

    def show_item_and_parents(self, item):
        item.setHidden(False)
        parent = item.parent()
        while parent:
            parent.setHidden(False)
            parent.setExpanded(True)
            parent = parent.parent()

    def reset_item_visuals(self, item):
        """恢复默认颜色"""
        node_type = item.text(1)
        if "constraint" in node_type.lower():
            item.setForeground(0, QtGui.QColor("#d4a5ff"))  # Purple
        elif node_type == "joint":
            item.setForeground(0, QtGui.QColor("#85c9e0"))  # Blue
        else:
            item.setForeground(0, QtGui.QColor("#cccccc"))  # Grey

    # =========================================================================
    # Core Logic
    # =========================================================================

    def sync_outliner(self):
        try:
            mel.eval('if (`runTimeCommand -exists showSelectedInOutliner`) showSelectedInOutliner;')
        except Exception:
            pass

    def get_immediate_driver(self, node_attr):
        connections = cmds.listConnections(node_attr, source=True, destination=False, plugs=True)
        if not connections:
            return None, None

        driver_plug = connections[0]
        driver_node = driver_plug.split(".")[0]
        ls = cmds.ls(driver_node, long=True)
        driver_full_path = ls[0] if ls else driver_node

        node_type = cmds.nodeType(driver_node)

        if node_type == 'unitConversion':
            return self.get_immediate_driver(f"{driver_node}.input")

        return driver_full_path, driver_node

    def get_constraint_targets(self, constraint_node):
        targets = cmds.listConnections(f"{constraint_node}.target", source=True, destination=False) or []
        targets = list(set(targets))

        target_info = []
        constraint_short_name = constraint_node.split("|")[-1]

        for t in targets:
            ls_t = cmds.ls(t, long=True)
            full_path = ls_t[0] if ls_t else t
            short_name = full_path.split("|")[-1]
            if short_name == constraint_short_name: continue
            target_info.append((full_path, short_name))

        return target_info

    def get_driven_data(self, node):
        node_type = cmds.nodeType(node)
        display_list = []
        driver_data_list = []

        if "constraint" in node_type.lower():
            target_info = self.get_constraint_targets(node)
            if target_info:
                target_names = [t[1] for t in target_info]
                display_list.append(f"<- {', '.join(target_names)}")
                for full_path, short_name in target_info:
                    driver_data_list.append({'label': short_name, 'driver_path': full_path})
        else:
            aggregator = {}
            attrs_to_check = ['tx', 'ty', 'tz', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'v']
            for attr in attrs_to_check:
                if cmds.attributeQuery(attr, node=node, exists=True):
                    driver_path, driver_name = self.get_immediate_driver(f"{node}.{attr}")
                    if driver_path:
                        if driver_path not in aggregator:
                            aggregator[driver_path] = {'short_name': driver_name, 'attrs': []}
                        aggregator[driver_path]['attrs'].append(attr)

            for driver_path, data in aggregator.items():
                attrs_str = ", ".join(data['attrs'])
                driver_name = data['short_name']
                driver_type = cmds.nodeType(driver_path)

                if "constraint" in driver_type.lower():
                    targets = self.get_constraint_targets(driver_path)
                    if targets:
                        target_names = [t[1] for t in targets]
                        display_list.append(f"{attrs_str} <- {driver_name}, {', '.join(target_names)}")
                        for t_path, t_name in targets:
                            driver_data_list.append(
                                {'label': f"{attrs_str} <- {t_name} ({driver_name})", 'driver_path': t_path})
                    else:
                        display_list.append(f"{attrs_str} <- {driver_name} (No Target)")
                        driver_data_list.append(
                            {'label': f"{attrs_str} <- {driver_name} (Broken)", 'driver_path': driver_path})
                else:
                    display_list.append(f"{attrs_str} <- {driver_name}")
                    driver_data_list.append({'label': f"{attrs_str} <- {driver_name}", 'driver_path': driver_path})

        return " ; ".join(display_list), driver_data_list

    def get_short_name(self, full_path):
        return full_path.split("|")[-1]

    def get_locked_attrs(self, node):
        locked = []
        for attr in ['tx', 'ty', 'tz', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz', 'v']:
            if cmds.attributeQuery(attr, node=node, exists=True):
                if cmds.getAttr(f"{node}.{attr}", lock=True):
                    locked.append(attr)
        return ", ".join(locked) if locked else ""

    def build_tree_recursive(self, maya_node, parent_item):
        short_name = self.get_short_name(maya_node)
        node_type = cmds.nodeType(maya_node)
        locked_str = self.get_locked_attrs(maya_node)
        driven_str, driven_data = self.get_driven_data(maya_node)

        item = QtWidgets.QTreeWidgetItem(parent_item)
        item.setText(0, short_name)
        item.setText(1, node_type)
        item.setText(2, locked_str)
        item.setText(3, driven_str)

        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, maya_node)
        item.setData(3, QtCore.Qt.ItemDataRole.UserRole, driven_data)

        # Initial Coloring
        self.reset_item_visuals(item)

        if locked_str: item.setForeground(2, QtGui.QColor("#ff6b6b"))
        if driven_str: item.setForeground(3, QtGui.QColor("#ffb86c"))

        children = cmds.listRelatives(maya_node, children=True, fullPath=True)
        if children:
            for child in children:
                self.build_tree_recursive(child, item)

    def refresh_tree(self):
        self.tree_widget.clear()
        self.tree_widget.setSortingEnabled(False)

        selection = cmds.ls(sl=True, long=True)
        nodes = selection if selection else [x for x in cmds.ls(assemblies=True, long=True) if
                                             x not in ['|persp', '|top', '|front', '|side']]

        title_suffix = "Selected" if selection else "All"
        self.setWindowTitle(f"Hierarchy Inspector - [{title_suffix}]")

        for node in nodes:
            self.build_tree_recursive(node, self.tree_widget)

        # Apply filters after rebuild
        self.apply_filters()

        if selection and not self.search_bar.text():
            self.tree_widget.expandAll()

    def expand_all(self):
        self.tree_widget.expandAll()

    def collapse_all(self):
        self.tree_widget.collapseAll()

    def on_item_clicked(self, item, column):
        node_path = item.data(0, QtCore.Qt.ItemDataRole.UserRole)

        if column == 3:
            driver_data = item.data(3, QtCore.Qt.ItemDataRole.UserRole)
            if driver_data:
                self.show_driver_menu(driver_data)
                return

        if node_path and cmds.objExists(node_path):
            final_selected = self.tree_widget.selectedItems()
            paths = [i.data(0, QtCore.Qt.ItemDataRole.UserRole) for i in final_selected]
            paths = [p for p in paths if p]

            if paths:
                cmds.select(paths)
                self.sync_outliner()

    def show_driver_menu(self, driver_data):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet("QMenu { padding: 5px; font-weight: bold; }")

        header = QtGui.QAction("Jump To Driver:", self)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()

        for data in driver_data:
            action = QtGui.QAction(data['label'], self)
            action.triggered.connect(lambda c=False, p=data['driver_path']: self.select_driver(p))
            menu.addAction(action)

        menu.exec(QtGui.QCursor.pos())

    def select_driver(self, full_path):
        if cmds.objExists(full_path):
            cmds.select(full_path)
            self.sync_outliner()
            cmds.inViewMessage(amg=f'<span style=\"color: #00FF00;\">Jumped to: {full_path.split("|")[-1]}</span>',
                               pos='midCenter', fade=True)

    def copy_to_md(self, only_selected=False):
        result_text = ""
        is_simple = self.chk_export_simple.isChecked()
        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree_widget)

        has_items = False
        while iterator.value():
            item = iterator.value()

            if only_selected and not item.isSelected():
                iterator += 1
                continue

            # 简单策略：如果需要导出，就导出。注意：通常隐藏项（被过滤的）不应导出。
            if item.isHidden():
                iterator += 1
                continue

            has_items = True

            depth = 0
            p = item.parent()
            while p:
                depth += 1
                p = p.parent()

            indent = "\t" * depth
            name = item.text(0)
            typ = item.text(1)
            type_part = f" ({typ})"

            if is_simple:
                result_text += f"{indent}- {name}{type_part}\n"
            else:
                locked = item.text(2)
                driven = item.text(3)
                l_part = f" 🔒 `{locked}`" if locked else ""
                d_part = f" ← {driven}" if driven else ""
                result_text += f"{indent}- {name}{type_part}{l_part}{d_part}\n"

            iterator += 1

        if not has_items:
            cmds.warning("No visible items to export.")
            return

        QtWidgets.QApplication.clipboard().setText(result_text)
        cmds.inViewMessage(amg='<span style=\"color: #00FF00;\">Markdown format copied!</span>', pos='midCenter',
                           fade=True)


# Startup
inspector_mod_win = None


def close_tool():
    global inspector_mod_win
    if inspector_mod_win is not None:
        try:
            inspector_mod_win.close()
            inspector_mod_win.deleteLater()
        except RuntimeError:
            # Qt object may already have been deleted by Maya.
            pass
        finally:
            inspector_mod_win = None


def show_tool():
    global inspector_mod_win
    close_tool()
    inspector_mod_win = MayaHierarchyInspectorExportMod()
    inspector_mod_win.show()
    return inspector_mod_win


if __name__ == "__main__":
    show_tool()
