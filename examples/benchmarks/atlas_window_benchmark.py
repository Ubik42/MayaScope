"""Reproducible Maya 2025/PySide6 benchmark for the production Atlas view."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.graph import get_graph_index, invalidate_graph_indexes
from MayaScope.model import SceneEdge, SceneNode, SceneSnapshot
from MayaScope.qt_compat import QtCore, QtGui, QtWidgets
from MayaScope.ui.atlas import MAX_RENDER_EDGES, MAX_RENDER_NODES, SpectralAtlasView
from MayaScope.ui.foundation import ensure_ui_fonts


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _build_snapshot(node_count: int, fanout: int) -> SceneSnapshot:
    if node_count < MAX_RENDER_NODES + 2:
        raise ValueError("node-count must exceed the Atlas render window")
    if fanout <= 0 or fanout >= node_count:
        raise ValueError("fanout must be between 1 and node-count - 1")
    identities = tuple("bench-%06d" % index for index in range(node_count))
    nodes = tuple(
        SceneNode(identity, "制作节点_%06d" % index, "network")
        for index, identity in enumerate(identities)
    )
    edges = tuple(
        SceneEdge(identities[source], identities[(source + offset) % node_count])
        for source in range(node_count)
        for offset in range(1, fanout + 1)
    )
    return SceneSnapshot.build(
        nodes,
        edges,
        source_scene="atlas-scale-benchmark.ma",
        snapshot_id="atlas-scale-%s-%s" % (node_count, fanout),
    )


def _render(view: SpectralAtlasView, width: int, height: int, target: Path | None):
    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#07070F"))
    painter = QtGui.QPainter(image)
    started = time.perf_counter()
    try:
        view.render(painter)
    finally:
        painter.end()
    elapsed = _elapsed_ms(started)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(target)):
            raise RuntimeError("无法保存 Atlas 基准截图：%s" % target)
    return elapsed


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_benchmark(
    *,
    node_count: int,
    fanout: int,
    width: int,
    height: int,
    output: Path | None = None,
    screenshot: Path | None = None,
) -> dict:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ensure_ui_fonts()
    snapshot_started = time.perf_counter()
    snapshot = _build_snapshot(node_count, fanout)
    snapshot_ms = _elapsed_ms(snapshot_started)

    index_started = time.perf_counter()
    graph = get_graph_index(snapshot, ("dg", "dag"))
    ranking = graph.ranked_node_ids()
    index_ms = _elapsed_ms(index_started)

    view = SpectralAtlasView()
    view.set_motion_enabled(False)
    view.resize(width, height)
    view.show()
    app.processEvents()
    try:
        first_started = time.perf_counter()
        view.set_snapshot(snapshot, ())
        app.processEvents()
        first_apply_ms = _elapsed_ms(first_started)
        first_stats = view.last_apply_stats
        first_raster_ms = _render(view, width, height, None)

        unchanged_started = time.perf_counter()
        view.set_snapshot(snapshot, ())
        app.processEvents()
        unchanged_apply_ms = _elapsed_ms(unchanged_started)
        unchanged_stats = view.last_apply_stats

        folded_id = ranking[-1]
        transform_before = view.transform().m11()
        swap_started = time.perf_counter()
        view.select_node_ids((folded_id,), center=False)
        app.processEvents()
        folded_swap_ms = _elapsed_ms(swap_started)
        folded_stats = view.last_apply_stats
        folded_raster_ms = _render(view, width, height, screenshot)
        camera_preserved = abs(view.transform().m11() - transform_before) < 1e-9

        contracts = {
            "索引与排名小于 5 秒": index_ms < 5000.0,
            "首次前台应用小于 250 ms": first_apply_ms < 250.0,
            "无变化换窗小于 50 ms": unchanged_apply_ms < 50.0,
            "折叠焦点换入小于 100 ms": folded_swap_ms < 100.0,
            "单帧真实栅格化小于 250 ms": folded_raster_ms < 250.0,
            "节点物化未超过预算": len(view._node_items) <= MAX_RENDER_NODES,
            "连线物化未超过预算": len(view._edge_items) <= MAX_RENDER_EDGES,
            "折叠焦点已换入": folded_id in view._node_items,
            "无变化节点全部复用": unchanged_stats.reused_nodes == len(view._node_items),
            "语义换窗保持视角": camera_preserved and folded_stats.camera_preserved,
        }
        payload = {
            "format": "mayascope.atlas-window-benchmark",
            "schema_version": 1,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "runtime": {
                "python": sys.version.split()[0],
                "executable": sys.executable,
                "qt": QtCore.qVersion(),
                "platform": platform.platform(),
            },
            "input": {
                "nodes": len(snapshot.nodes),
                "edges": len(snapshot.edges),
                "fanout": fanout,
                "window": [width, height],
            },
            "budgets": {
                "render_nodes": MAX_RENDER_NODES,
                "render_edges": MAX_RENDER_EDGES,
            },
            "timings_ms": {
                "snapshot_build": round(snapshot_ms, 3),
                "index_and_rank": round(index_ms, 3),
                "first_apply": round(first_apply_ms, 3),
                "first_raster": round(first_raster_ms, 3),
                "unchanged_apply": round(unchanged_apply_ms, 3),
                "folded_swap": round(folded_swap_ms, 3),
                "folded_raster": round(folded_raster_ms, 3),
            },
            "first_apply": asdict(first_stats),
            "unchanged_apply": asdict(unchanged_stats),
            "folded_swap": asdict(folded_stats),
            "folded_focus_id": folded_id,
            "contracts": contracts,
            "ok": all(contracts.values()),
            "screenshot": str(screenshot.resolve()) if screenshot else "",
        }
    finally:
        view.clear_snapshot()
        view.close()
        view.deleteLater()
        app.processEvents()
        invalidate_graph_indexes(snapshot.snapshot_id)
    if output is not None:
        _atomic_json(output.resolve(), payload)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MayaScope Atlas 增量语义窗基准")
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument("--fanout", type=int, default=10)
    parser.add_argument("--width", type=int, default=1480)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_benchmark(
            node_count=args.nodes,
            fanout=args.fanout,
            width=args.width,
            height=args.height,
            output=args.output,
            screenshot=args.screenshot,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
