"""Scene Clinic rail and evidence surface for the MayaScope workspace."""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from ..analysis.clinic import (
    ClinicReport,
    DEFAULT_PROFILES,
    DEFAULT_REGISTRY,
    RuleProfile,
    RuleSpec,
)
from ..analysis.incidents import Incident
from ..analysis.rules import Issue
from ..presentation.evidence import ClinicEvidencePresenter, EvidencePanelState
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import COLORS, qt_enum as _qt_enum


class ClinicSpectrum(QtWidgets.QWidget):
    """Compact live glyph for rule channels, findings, and isolated failures."""

    CHANNELS = ("integrity", "performance", "references", "pipeline")

    def __init__(self, registry=DEFAULT_REGISTRY, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setAccessibleName("场景诊所规则光谱")
        self.setFixedHeight(48)
        self._report: Optional[ClinicReport] = None
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(55)

    def set_report(self, report: Optional[ClinicReport]):
        self._report = report
        self.update()

    def set_motion_enabled(self, enabled: bool):
        if enabled:
            self._timer.start(55)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def _tick(self):
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#09070F"))
        specs = {spec.id: spec for spec in self.registry.specs}
        runs = {run.rule_id: run for run in self._report.runs} if self._report else {}
        failed = {item.rule_id for item in self._report.failures} if self._report else set()
        skipped = set(self._report.skipped_rule_ids) if self._report else set()
        channel_values = {name: [0, 0, 0.0] for name in self.CHANNELS}
        for rule_id, run in runs.items():
            category = specs[rule_id].category
            channel_values[category][0] += 1
            channel_values[category][1] += run.issue_count
            channel_values[category][2] += run.duration_ms
        colors = (COLORS["acid"], COLORS["orange"], COLORS["cyan"], COLORS["violet"])
        lane = self.width() / 4.0
        for index, category in enumerate(self.CHANNELS):
            x = index * lane + 5
            width = lane - 10
            run_count, issue_count, _duration = channel_values[category]
            color = QtGui.QColor(colors[index])
            related = [spec.id for spec in self.registry.specs if spec.category == category]
            if any(rule_id in failed for rule_id in related):
                color = QtGui.QColor("#FF335F")
            elif related and all(rule_id in skipped for rule_id in related):
                color = QtGui.QColor("#393342")
            painter.setPen(QtGui.QPen(QtGui.QColor(color), 1.0))
            painter.setBrush(QtGui.QColor(color.red(), color.green(), color.blue(), 30 + min(120, issue_count * 35)))
            painter.drawRoundedRect(QtCore.QRectF(x, 5, width, 28), 4, 4)
            if run_count:
                sweep = x + ((self._phase + index * 0.19) % 1.0) * width
                painter.fillRect(QtCore.QRectF(sweep - 8, 6, 16, 26), QtGui.QColor(color.red(), color.green(), color.blue(), 32))
            painter.setPen(color)
            painter.drawText(QtCore.QRectF(x, 6, width, 12), _qt_enum(QtCore.Qt, "AlignCenter"), str(issue_count))
            painter.setPen(COLORS["muted"])
            channel_name = {"integrity": "完整性", "performance": "性能", "references": "引用", "pipeline": "流程"}.get(category, category)
            painter.drawText(QtCore.QRectF(x, 34, width, 11), _qt_enum(QtCore.Qt, "AlignCenter"), channel_name)


class ClinicRuleArray(QtWidgets.QFrame):
    runRequested = QtCore.Signal()
    ruleFocusRequested = QtCore.Signal(str)

    def __init__(self, registry=DEFAULT_REGISTRY, profiles=DEFAULT_PROFILES, config_source="built-in", config_fingerprint="built-in", parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setObjectName("ClinicArray")
        self.setAccessibleName("场景诊所规则阵列")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("场景诊所  /  规则阵列")
        title.setObjectName("ClinicTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.config_badge = QtWidgets.QLabel(
            "内置规则" if config_source == "built-in" else "团队规则 %s" % config_fingerprint[:7].upper()
        )
        self.config_badge.setObjectName("ClinicConfigBadge")
        self.config_badge.setToolTip("诊所规则来源：%s\n指纹：%s" % (config_source, config_fingerprint))
        header.addWidget(self.config_badge)
        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.setObjectName("ClinicProfile")
        for profile in profiles:
            self.profile_combo.addItem(profile.title, profile)
        self.profile_combo.setToolTip("切换适合当前制作阶段的规则组合")
        self.profile_combo.currentIndexChanged.connect(self._apply_profile)
        header.addWidget(self.profile_combo)
        layout.addLayout(header)
        self.contract_band = QtWidgets.QFrame()
        self.contract_band.setObjectName("SceneContractBand")
        contract_layout = QtWidgets.QGridLayout(self.contract_band)
        contract_layout.setContentsMargins(7, 4, 7, 4)
        contract_layout.setHorizontalSpacing(5)
        contract_layout.setVerticalSpacing(3)
        self.contract_title = QtWidgets.QLabel("制片信号")
        self.contract_title.setObjectName("SceneContractTitle")
        contract_layout.addWidget(self.contract_title, 0, 0)
        self.setting_chips = []
        positions = ((0, 1), (0, 2), (0, 3), (1, 0))
        for text, (row, column) in zip(
            ("帧率 · —", "尺度 · —", "上轴 · —", "色彩 · —"), positions
        ):
            chip = QtWidgets.QLabel(text)
            chip.setObjectName("SceneSettingChip")
            contract_layout.addWidget(chip, row, column)
            self.setting_chips.append(chip)
        self.dependency_chip = QtWidgets.QPushButton("依赖谱系 · —")
        self.dependency_chip.setObjectName("SceneDependencyChip")
        self.dependency_chip.setCursor(
            QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor"))
        )
        self.dependency_chip.setToolTip("点击定位外部依赖健康诊断规则")
        self.dependency_chip.clicked.connect(self._focus_dependency_health)
        contract_layout.addWidget(self.dependency_chip, 2, 0, 1, 4)
        self.plugin_chip = QtWidgets.QPushButton("插件幽灵 · —")
        self.plugin_chip.setObjectName("ScenePluginChip")
        self.plugin_chip.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.plugin_chip.setToolTip("点击定位缺失插件诊断规则")
        self.plugin_chip.clicked.connect(self._focus_missing_plugins)
        contract_layout.addWidget(self.plugin_chip, 1, 2, 1, 2)
        self.reference_chip = QtWidgets.QPushButton("引用轨道 · —")
        self.reference_chip.setObjectName("SceneReferenceChip")
        self.reference_chip.setCursor(
            QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor"))
        )
        self.reference_chip.setToolTip("点击定位引用健康诊断规则")
        self.reference_chip.clicked.connect(self._focus_reference_health)
        contract_layout.addWidget(self.reference_chip, 3, 0, 1, 4)
        self._reference_focus_rule = "unloaded-references"
        self._dependency_focus_rule = "missing-external-files"
        for column in range(4):
            contract_layout.setColumnStretch(column, 1)
        layout.addWidget(self.contract_band)
        self.spectrum = ClinicSpectrum(registry)
        layout.addWidget(self.spectrum)
        self.rules_scroll = QtWidgets.QScrollArea()
        self.rules_scroll.setObjectName("RuleScroll")
        self.rules_scroll.setWidgetResizable(True)
        self.rules_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.rules_scroll.setHorizontalScrollBarPolicy(_qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"))
        self.rules_scroll.setFixedHeight(82)
        rules_host = QtWidgets.QWidget()
        rules_host.setMinimumWidth(0)
        rules_host.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        grid = QtWidgets.QGridLayout()
        rules_host.setLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.rule_buttons = {}
        for index, spec in enumerate(registry.specs):
            button = QtWidgets.QPushButton(spec.title)
            button.setObjectName("RuleToggle")
            button.setMinimumWidth(0)
            button.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            button.setCheckable(True)
            button.setChecked(spec.default_enabled)
            category = {"integrity": "完整性", "performance": "性能", "references": "引用", "pipeline": "流程"}.get(spec.category, spec.category)
            confidence = {"deterministic": "确定性", "strong": "高置信", "heuristic": "启发式"}.get(spec.confidence, spec.confidence)
            cost = {"cheap": "轻量扫描", "moderate": "常规扫描", "expensive": "深度扫描"}.get(spec.cost, spec.cost)
            button.setToolTip("%s · %s · %s" % (category, confidence, cost))
            button.toggled.connect(self._sync_run_state)
            grid.addWidget(button, index // 2, index % 2)
            self.rule_buttons[spec.id] = button
        self.rules_scroll.setWidget(rules_host)
        layout.addWidget(self.rules_scroll)
        footer = QtWidgets.QHBoxLayout()
        self.telemetry = QtWidgets.QLabel("等待场景快照")
        self.telemetry.setObjectName("ClinicTelemetry")
        footer.addWidget(self.telemetry, 1)
        self.run_button = QtWidgets.QPushButton("扫描快照")
        self.run_button.setObjectName("ClinicRun")
        self.run_button.clicked.connect(self.runRequested)
        footer.addWidget(self.run_button)
        layout.addLayout(footer)
        self.setMinimumHeight(268)

    def set_scene_settings(
        self, settings, dependencies=(), lifecycle=None, unknown_plugins=(),
        references=(), nodes=(),
    ):
        fps = "%.3f" % settings.frames_per_second if settings.frames_per_second else "—"
        fps = fps.rstrip("0").rstrip(".")
        color = (
            "已启用" if settings.color_management_enabled is True
            else "已停用" if settings.color_management_enabled is False
            else "不可读取"
        )
        values = (
            "帧率 · %s / %s" % (settings.time_unit or "—", fps),
            "尺度 · %s / %s" % (settings.linear_unit or "—", settings.angular_unit or "—"),
            "上轴 · %s" % ((settings.up_axis or "—").upper()),
            "色彩 · %s" % ("开" if color == "已启用" else "关" if color == "已停用" else "—"),
        )
        for chip, value in zip(self.setting_chips, values):
            chip.setText(value)
        dependencies = tuple(dependencies)
        missing = sum(item.exists is False for item in dependencies)
        risky = sum(
            item.path_kind == "network"
            or (item.path_kind == "absolute" and item.inside_workspace is False)
            for item in dependencies
        )
        sequence_dependencies = sum(bool(item.sequence_pattern) for item in dependencies)
        gap_sequences = sum(
            item.sequence_scan_complete and bool(item.sequence_missing_count)
            for item in dependencies
        )
        missing_members = sum(
            int(item.sequence_missing_count or 0) for item in dependencies
            if item.sequence_scan_complete
        )
        self.dependency_chip.setText(
            "依赖谱系 · %s / 序列 %s · 缺文件 %s · 缺帧 %s"
            % (len(dependencies), sequence_dependencies, missing, missing_members)
        )
        self.dependency_chip.setProperty("danger", bool(missing))
        self.dependency_chip.setProperty("alert", bool(gap_sequences or risky) and not missing)
        self._dependency_focus_rule = (
            "missing-external-files" if missing
            else "external-sequence-gaps" if gap_sequences
            else "nonportable-external-files"
        )
        self.dependency_chip.setToolTip(
            "外部依赖：%s · 序列/缓存：%s\n缺失文件：%s · 不完整序列：%s · 缺失成员：%s\n"
            "不可移植路径：%s\n点击定位当前最高风险依赖规则"
            % (
                len(dependencies), sequence_dependencies, missing,
                gap_sequences, missing_members, risky,
            )
        )
        self.dependency_chip.style().unpolish(self.dependency_chip)
        self.dependency_chip.style().polish(self.dependency_chip)
        unknown_plugins = tuple(unknown_plugins)
        unknown_types = sum(len(item.node_types) for item in unknown_plugins)
        self.plugin_chip.setText(
            "插件幽灵 · %s / 类型 %s" % (len(unknown_plugins), unknown_types)
        )
        self.plugin_chip.setProperty("alert", bool(unknown_plugins))
        self.plugin_chip.setToolTip(
            "场景记录的缺失插件：%s\n点击定位缺失插件诊断规则"
            % (", ".join(item.name for item in unknown_plugins) if unknown_plugins else "无")
        )
        self.plugin_chip.style().unpolish(self.plugin_chip)
        self.plugin_chip.style().polish(self.plugin_chip)
        references = tuple(references)
        nodes = tuple(nodes)
        source_files = {
            (item.canonical_path or item.resolved_path).replace("\\", "/").casefold()
            for item in references
        }
        missing_references = tuple(item for item in references if item.exists is False)
        unloaded_references = tuple(item for item in references if not item.loaded)
        copy_instances = sum(item.copy_number > 0 for item in references)
        reference_namespaces = {
            item.namespace.strip(":") for item in references if item.namespace.strip(":")
        }
        intruders = []
        for node in nodes:
            if node.referenced or not node.namespace:
                continue
            parts = node.namespace.split(":")
            if any(
                ":".join(parts[:depth]) in reference_namespaces
                for depth in range(len(parts), 0, -1)
            ):
                intruders.append(node)
        intruders = tuple(intruders)
        self.reference_chip.setText(
            "引用轨道 · %s 实例 / %s 源 · 缺 %s · 越界 %s"
            % (len(references), len(source_files), len(missing_references), len(intruders))
        )
        self.reference_chip.setProperty("danger", bool(missing_references))
        self.reference_chip.setProperty(
            "alert", bool(intruders or unloaded_references) and not missing_references
        )
        self._reference_focus_rule = (
            "missing-reference-files" if missing_references
            else "reference-namespace-intrusion" if intruders
            else "unloaded-references" if unloaded_references
            else "nested-reference-depth"
        )
        self.reference_chip.setToolTip(
            "引用实例：%s · 规范化源文件：%s · 复制实例：%s\n"
            "缺失：%s · 未加载：%s · namespace 越界：%s\n点击定位当前最高风险引用规则"
            % (
                len(references), len(source_files), copy_instances,
                len(missing_references), len(unloaded_references), len(intruders),
            )
        )
        self.reference_chip.style().unpolish(self.reference_chip)
        self.reference_chip.style().polish(self.reference_chip)
        dirty = bool(lifecycle and lifecycle.modified is True)
        self.contract_title.setText("制片信号 · 未保存" if dirty else "制片信号")
        self.contract_band.setProperty("dirty", dirty)
        self.contract_band.style().unpolish(self.contract_band)
        self.contract_band.style().polish(self.contract_band)
        self.contract_band.setToolTip(
            "渲染空间：%s\n视图变换：%s\nOCIO 配置：%s\n外部依赖：%s 项 · 序列 %s 项 · 缺失文件 %s 项 · 缺失帧 %s · 可移植风险 %s 项\n缺失插件：%s 项 · 注册节点类型 %s 项\n引用：%s 实例 / %s 源 · 缺失 %s · namespace 越界 %s\n内存状态：%s"
            % (
                settings.rendering_space or "不可读取",
                settings.view_transform or "不可读取",
                settings.color_config_path or "Maya 内置 / 不可读取",
                len(dependencies),
                sequence_dependencies,
                missing,
                missing_members,
                risky,
                len(unknown_plugins),
                unknown_types,
                len(references),
                len(source_files),
                len(missing_references),
                len(intruders),
                "有未保存修改" if dirty else "与磁盘一致 / 不可读取",
            )
        )

    def _focus_dependency_health(self):
        button = self.rule_buttons.get(self._dependency_focus_rule)
        if button is None:
            return
        button.setChecked(True)
        button.setFocus()
        self.rules_scroll.ensureWidgetVisible(button)
        self.telemetry.setText("已定位依赖谱系规则  ·  点击“扫描快照”刷新证据")
        self.ruleFocusRequested.emit(self._dependency_focus_rule)

    def _focus_missing_plugins(self):
        button = self.rule_buttons.get("missing-plugin-requirements")
        if button is None:
            return
        button.setChecked(True)
        button.setFocus()
        self.rules_scroll.ensureWidgetVisible(button)
        self.telemetry.setText("已定位缺失插件规则  ·  点击“扫描快照”刷新证据")
        self.ruleFocusRequested.emit("missing-plugin-requirements")

    def _focus_reference_health(self):
        button = self.rule_buttons.get(self._reference_focus_rule)
        if button is None:
            return
        button.setChecked(True)
        button.setFocus()
        self.rules_scroll.ensureWidgetVisible(button)
        self.telemetry.setText("已定位引用健康规则  ·  点击“扫描快照”刷新证据")
        self.ruleFocusRequested.emit(self._reference_focus_rule)

    def enabled_rule_ids(self):
        return tuple(rule_id for rule_id, button in self.rule_buttons.items() if button.isChecked())

    def _sync_run_state(self, *_args):
        self.run_button.setEnabled(bool(self.enabled_rule_ids()))

    def current_profile(self) -> RuleProfile:
        return self.profile_combo.currentData()

    def _apply_profile(self, index: int):
        profile = self.profile_combo.itemData(index)
        if not profile:
            return
        enabled = set(profile.rule_ids)
        for rule_id, button in self.rule_buttons.items():
            button.blockSignals(True)
            button.setChecked(rule_id in enabled)
            button.blockSignals(False)
        self.telemetry.setText("%s已就绪  ·  点击扫描" % profile.title)
        self.profile_combo.setToolTip(profile.description)
        self._sync_run_state()

    def set_compact(self, compact: bool):
        for button in self.rule_buttons.values():
            button.setVisible(not compact)
        self.rules_scroll.setVisible(not compact)
        self.config_badge.setVisible(not compact)
        self.contract_band.setVisible(not compact)
        self.telemetry.setVisible(not compact)
        self.setMinimumHeight(132 if compact else 248)
        self.setMaximumHeight(132 if compact else 290)

    def set_config_error(self, message: str):
        self.config_badge.setText("配置已回退")
        self.config_badge.setProperty("error", True)
        self.config_badge.setToolTip(message)
        self.config_badge.style().unpolish(self.config_badge)
        self.config_badge.style().polish(self.config_badge)

    def set_report(self, report: ClinicReport, incident_count: int = 0):
        self.spectrum.set_report(report)
        if report.failures:
            text = "%s 条规则异常  ·  %s 项发现" % (len(report.failures), len(report.issues))
        else:
            text = "%s 条规则  ·  %s 个事件簇  ·  %s 项发现  ·  %.2f ms" % (len(report.runs), incident_count, len(report.issues), report.duration_ms)
        self.telemetry.setText(text)

    def set_motion_enabled(self, enabled: bool):
        self.spectrum.set_motion_enabled(enabled)



class IncidentCard(QtWidgets.QFrame):
    activated = QtCore.Signal(object)

    def __init__(self, incident: Incident, ordinal: int, parent=None):
        super().__init__(parent)
        self.incident = incident
        self.setObjectName("IncidentCard")
        self.setAccessibleName("事件簇：%s" % incident.title)
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        index = QtWidgets.QLabel(
            "事件簇 %02d  /  %s 项发现  /  %s 个节点"
            % (ordinal, len(incident.issue_ids), len(incident.affected_node_ids))
        )
        index.setObjectName("IncidentIndex")
        layout.addWidget(index)
        title = QtWidgets.QLabel(incident.title)
        title.setObjectName("IncidentTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        reason = QtWidgets.QLabel("  ·  ".join(item.value for item in incident.evidence[:2]))
        reason.setObjectName("IncidentReason")
        reason.setWordWrap(True)
        layout.addWidget(reason)

    def mousePressEvent(self, event):
        self.activated.emit(self.incident)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (
            _qt_enum(QtCore.Qt, "Key_Return"),
            _qt_enum(QtCore.Qt, "Key_Space"),
        ):
            self.activated.emit(self.incident)
            event.accept()
            return
        super().keyPressEvent(event)


class IssueCard(QtWidgets.QFrame):
    activated = QtCore.Signal(object)

    def __init__(self, issue: Issue, spec: Optional[RuleSpec] = None, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("IssueCard")
        self.setAccessibleName("诊断发现：%s" % issue.title)
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(5)
        title = QtWidgets.QLabel(issue.title)
        title.setObjectName("IssueTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        severity_name = {
            "INFO": "提示",
            "WARNING": "警告",
            "ERROR": "错误",
            "CRITICAL": "严重",
        }.get(issue.severity.name, issue.severity.name)
        severity = QtWidgets.QLabel(
            "%s  /  %s 个信号" % (severity_name, len(issue.affected_node_ids))
        )
        severity.setObjectName("Severity%s" % issue.severity.name.title())
        layout.addWidget(severity)
        if spec:
            category = {
                "integrity": "完整性",
                "performance": "性能",
                "references": "引用",
                "pipeline": "流程",
            }.get(spec.category, spec.category)
            confidence = {
                "deterministic": "确定性",
                "strong": "高置信",
                "heuristic": "启发式",
            }.get(spec.confidence, spec.confidence)
            cost = {
                "cheap": "轻量",
                "moderate": "常规",
                "expensive": "深度",
            }.get(spec.cost, spec.cost)
            repair = {
                "diagnostic": "仅诊断",
                "previewed": "可预览修复",
            }.get(spec.repair_kind, spec.repair_kind)
            contract = QtWidgets.QLabel(
                "%s  ·  %s  ·  %s扫描  ·  %s"
                % (category, confidence, cost, repair)
            )
            contract.setObjectName("IssueContract")
            contract.setWordWrap(True)
            layout.addWidget(contract)

    def mousePressEvent(self, event):
        self.activated.emit(self.issue)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (
            _qt_enum(QtCore.Qt, "Key_Return"),
            _qt_enum(QtCore.Qt, "Key_Space"),
        ):
            self.activated.emit(self.issue)
            event.accept()
            return
        super().keyPressEvent(event)


class SceneClinicView(QtWidgets.QFrame):
    """Own the Clinic cards and the shared evidence/action surface."""

    issueActivated = QtCore.Signal(object)
    incidentActivated = QtCore.Signal(object)
    planRequested = QtCore.Signal()
    rollbackRequested = QtCore.Signal()

    def __init__(
        self,
        registry=DEFAULT_REGISTRY,
        profiles=DEFAULT_PROFILES,
        config_source="built-in",
        config_fingerprint="built-in",
        parent=None,
        *,
        rule_array=None,
    ):
        super().__init__(parent)
        self.setObjectName("IssueRail")
        self.setAccessibleName("场景诊所问题与因果证据")
        self.setMinimumWidth(320)
        self.setMaximumWidth(430)
        self.rule_array = rule_array or ClinicRuleArray(
            registry,
            profiles,
            config_source,
            config_fingerprint,
            self,
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        self.eyebrow = QtWidgets.QLabel("问题证据")
        self.eyebrow.setObjectName("Eyebrow")
        layout.addWidget(self.eyebrow)
        self.heading = QtWidgets.QLabel("等待场景信号")
        self.heading.setObjectName("RailHeading")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        layout.addWidget(self.rule_array)

        self.issue_scroll = QtWidgets.QScrollArea()
        self.issue_scroll.setWidgetResizable(True)
        self.issue_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.issue_scroll.setHorizontalScrollBarPolicy(
            _qt_enum(QtCore.Qt, "ScrollBarAlwaysOff")
        )
        self.issue_host = QtWidgets.QWidget()
        self.issue_host.setMinimumWidth(0)
        self.issue_host.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,
            QtWidgets.QSizePolicy.Preferred,
        )
        self.issue_list = QtWidgets.QVBoxLayout(self.issue_host)
        self.issue_list.setContentsMargins(0, 8, 0, 8)
        self.issue_list.setSpacing(9)
        self.issue_list.addStretch(1)
        self.issue_scroll.setWidget(self.issue_host)
        layout.addWidget(self.issue_scroll, 1)

        self.evidence = QtWidgets.QLabel("捕获场景后将在这里呈现因果证据。")
        self.evidence.setObjectName("Evidence")
        self.evidence.setWordWrap(True)
        self.evidence.setAlignment(
            _qt_enum(QtCore.Qt, "AlignLeft") | _qt_enum(QtCore.Qt, "AlignTop")
        )
        layout.addWidget(self.evidence)
        self.plan_button = QtWidgets.QPushButton("预览变更计划")
        self.plan_button.setObjectName("PlanButton")
        self.plan_button.setEnabled(False)
        self.plan_button.clicked.connect(self.planRequested)
        layout.addWidget(self.plan_button)
        self.rollback_button = QtWidgets.QPushButton("↶  回滚上次变更计划")
        self.rollback_button.setObjectName("RollbackButton")
        self.rollback_button.setVisible(False)
        self.rollback_button.clicked.connect(self.rollbackRequested)
        layout.addWidget(self.rollback_button)

    def set_compact(self, compact: bool):
        self.setMinimumWidth(270 if compact else 320)
        self.setMaximumWidth(330 if compact else 430)
        self.rule_array.set_compact(compact)

    def set_lens_mode(self, active: bool):
        """Give causal evidence the full rail while Lens is active."""
        self.eyebrow.setText("因果证据" if active else "问题证据")
        self.rule_array.setVisible(not active)
        self.issue_scroll.setVisible(not active)
        self.evidence.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Expanding if active else QtWidgets.QSizePolicy.Preferred,
        )

    def present(self, state: EvidencePanelState):
        self.heading.setText(state.heading)
        self.evidence.setText(state.body)
        self.plan_button.setText(state.action_label)
        self.plan_button.setEnabled(state.action_enabled)

    def set_heading(self, heading: str):
        if not heading.strip():
            raise ValueError("证据标题不能为空")
        self.heading.setText(heading)

    def set_body(self, body: str):
        if not body.strip():
            raise ValueError("证据正文不能为空")
        self.evidence.setText(body)

    def set_action(self, label: str, *, enabled: bool):
        if not label.strip():
            raise ValueError("证据操作文案不能为空")
        self.plan_button.setText(label)
        self.plan_button.setEnabled(enabled)

    def present_text(
        self,
        heading: str,
        body: str,
        *,
        action_label: str = "预览变更计划",
        action_enabled: bool = False,
    ):
        self.present(
            EvidencePanelState(
                heading=heading,
                body=body,
                action_label=action_label,
                action_enabled=action_enabled,
            )
        )

    def render_report(
        self,
        report: ClinicReport,
        incidents: Sequence[Incident],
        specs: Mapping[str, RuleSpec],
    ):
        self._clear_cards()
        issues_by_id = {issue.id: issue for issue in report.issues}
        for ordinal, incident in enumerate(incidents, 1):
            incident_card = IncidentCard(incident, ordinal)
            incident_card.activated.connect(self.incidentActivated)
            self.issue_list.insertWidget(self.issue_list.count() - 1, incident_card)
            for issue_id in incident.issue_ids:
                issue = issues_by_id.get(issue_id)
                if issue is None:
                    raise ValueError("事件簇引用了不存在的诊断：%s" % issue_id)
                card = IssueCard(issue, specs.get(issue.rule_id))
                card.activated.connect(self.issueActivated)
                self.issue_list.insertWidget(self.issue_list.count() - 1, card)
        self.present(ClinicEvidencePresenter.overview(report, incidents))

    def present_issue(self, issue: Issue, *, has_plan: bool):
        self.present(ClinicEvidencePresenter.issue(issue, has_plan=has_plan))

    def present_incident(
        self,
        incident: Incident,
        issue_map: Mapping[str, Issue],
        *,
        repairable_issue_count: int = 0,
    ):
        self.present(
            ClinicEvidencePresenter.incident(
                incident,
                issue_map,
                repairable_issue_count=repairable_issue_count,
            )
        )

    def _clear_cards(self):
        while self.issue_list.count() > 1:
            item = self.issue_list.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
