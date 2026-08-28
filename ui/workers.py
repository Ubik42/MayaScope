"""Qt worker adapters for bounded MayaScope background application jobs."""

from __future__ import annotations

from pathlib import Path

from ..analysis.clinic import ClinicCancelled
from ..analysis.graph import QueryCancelled, get_graph_index
from ..analysis.identity import build_host_identity_index
from ..analysis.incidents import cluster_issues
from ..qt_compat import QtCore
from ..runner import BisectSession


class BisectWorker(QtCore.QObject):
    probeCompleted = QtCore.Signal(object, object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, plan, cancel_event, root=None, journal_path=None):
        super().__init__()
        self.plan = plan
        self.cancel_event = cancel_event
        self.root = root
        self.journal_path = journal_path

    @QtCore.Slot()
    def run(self):
        try:
            session = (
                BisectSession.resume(self.journal_path)
                if self.journal_path
                else BisectSession(self.plan, root=self.root)
            )
            result = session.run(
                cancelled=self.cancel_event.is_set,
                progress=self.probeCompleted.emit,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class ClinicWorker(QtCore.QObject):
    progress = QtCore.Signal(int, int, str)
    finished = QtCore.Signal(object, object, object)
    cancelled = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, registry, snapshot, enabled_rule_ids, include_expensive, cancel_event):
        super().__init__()
        self.registry = registry
        self.snapshot = snapshot
        self.enabled_rule_ids = tuple(enabled_rule_ids)
        self.include_expensive = bool(include_expensive)
        self.cancel_event = cancel_event

    @QtCore.Slot()
    def run(self):
        try:
            if self.cancel_event.is_set():
                raise ClinicCancelled("场景诊所在图索引前被取消")
            get_graph_index(self.snapshot, cancelled=self.cancel_event.is_set)
            atlas_index = get_graph_index(
                self.snapshot,
                ("dg", "dag"),
                cancelled=self.cancel_event.is_set,
            )
            atlas_index.ranked_node_ids(cancelled=self.cancel_event.is_set)
            host_identity_index = build_host_identity_index(
                self.snapshot, cancelled=self.cancel_event.is_set
            )
            report = self.registry.evaluate(
                self.snapshot,
                enabled_rule_ids=self.enabled_rule_ids,
                include_expensive=self.include_expensive,
                cancelled=self.cancel_event.is_set,
                progress=self.progress.emit,
            )
            if self.cancel_event.is_set():
                raise ClinicCancelled("场景诊所在当前规则完成后被取消")
            incidents = cluster_issues(self.snapshot, report.issues)
        except (ClinicCancelled, QueryCancelled):
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(report, incidents, host_identity_index)


class ProjectQueueWorker(QtCore.QObject):
    progress = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self, plan_path, journal_path, report_dir, project_report, cancel_event
    ):
        super().__init__()
        self.plan_path = Path(plan_path)
        self.journal_path = Path(journal_path)
        self.report_dir = Path(report_dir)
        self.project_report = Path(project_report)
        self.cancel_event = cancel_event

    @QtCore.Slot()
    def run(self):
        try:
            from ..project_queue import run_project_plan

            journal = run_project_plan(
                self.plan_path,
                self.journal_path,
                self.report_dir,
                self.project_report,
                should_cancel=self.cancel_event.is_set,
                progress=self.progress.emit,
            )
        except Exception as exc:
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))
            return
        self.finished.emit(journal)


__all__ = ["BisectWorker", "ClinicWorker", "ProjectQueueWorker"]
