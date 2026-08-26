"""Build conservative post-open Bisect candidates from a SceneSnapshot."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import hashlib
from typing import Dict, Tuple

from ..model import BisectCandidate, BisectPlan, SceneSnapshot
from .isolated import RunnerError, sha256_file
from .maya_ascii import inspect_maya_ascii


DEFAULT_DAG_ROOTS = frozenset({"persp", "top", "front", "side"})


def build_post_open_bisect_plan(
    snapshot: SceneSnapshot,
    maya_executable: str,
    *,
    timeout_seconds: float = 120.0,
) -> BisectPlan:
    """Group local top-level DAG roots and references for copy-only probes.

    This plan can isolate evaluate/save/reopen failures. It deliberately does
    not claim it can modify a scene before Maya successfully opens the copy.
    """
    if not snapshot.source_scene:
        raise RunnerError("Crash Bisect requires a saved source scene")
    source = Path(snapshot.source_scene).expanduser().resolve()
    if not source.is_file():
        raise RunnerError("Crash Bisect source scene does not exist: %s" % source)
    node_map = snapshot.node_map
    dag_children: Dict[str, list] = defaultdict(list)
    dag_parents = set()
    for edge in snapshot.edges:
        if edge.relation != "dag":
            continue
        dag_children[edge.source_id].append(edge.target_id)
        dag_parents.add(edge.target_id)

    candidates = []
    for node in snapshot.nodes:
        if (
            not node.is_dag
            or node.id in dag_parents
            or node.referenced
            or node.name in DEFAULT_DAG_ROOTS
            or node.type_name not in {"transform", "joint"}
        ):
            continue
        descendants = []
        queue = deque((node.id,))
        seen = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            descendants.append(current)
            queue.extend(dag_children.get(current, ()))
        maya_name = node.dag_paths[0] if node.dag_paths else node.name
        candidates.append(
            BisectCandidate(
                id="dag:%s" % node.id,
                label=node.name,
                kind="top-level-dag",
                stable_node_ids=tuple(descendants),
                metadata={"maya_names": (maya_name,), "scope": "local top-level DAG"},
            )
        )
    for reference in snapshot.references:
        candidates.append(
            BisectCandidate(
                id="reference:%s" % reference.reference_node,
                label=reference.reference_node,
                kind="reference",
                stable_node_ids=reference.node_ids,
                metadata={
                    "reference_node": reference.reference_node,
                    "resolved_path": reference.resolved_path,
                    "loaded_at_capture": reference.loaded,
                },
            )
        )
    if not candidates:
        raise RunnerError("No safe post-open Bisect candidates were found")
    candidates.sort(key=lambda item: (item.kind, item.label, item.id))
    return BisectPlan(
        source_scene=str(source),
        source_sha256=sha256_file(source),
        candidates=tuple(candidates),
        maya_executable=str(Path(maya_executable).expanduser().resolve()),
        timeout_seconds=timeout_seconds,
        metadata={
            "source_snapshot_id": snapshot.snapshot_id,
            "captured_at": snapshot.captured_at,
            "capability": "post-open evaluate/save/reopen isolation",
            "open_crash_boundary": (
                "All candidates are present during initial open; pre-open .ma slicing is not enabled."
            ),
        },
    )


def _ascii_identity(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:14]
    return "%s:%s" % (prefix, digest)


def build_pre_open_ascii_bisect_plan(
    source_scene: str,
    maya_executable: str,
    *,
    timeout_seconds: float = 120.0,
) -> BisectPlan:
    """Plan candidates directly from .ma text before Maya opens the scene."""
    source = Path(source_scene).expanduser().resolve()
    document = inspect_maya_ascii(source)
    children: Dict[str, list] = defaultdict(list)
    for node in document.nodes:
        if node.parent_path:
            children[node.parent_path].append(node.full_path)
    candidates = []
    for node in document.nodes:
        if (
            node.parent_path
            or node.name in DEFAULT_DAG_ROOTS
            or node.type_name not in {"transform", "joint"}
        ):
            continue
        descendants = []
        queue = deque((node.full_path,))
        seen = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            descendants.append(_ascii_identity("ascii-node", current))
            queue.extend(children.get(current, ()))
        candidates.append(
            BisectCandidate(
                id=_ascii_identity("dag", node.full_path),
                label=node.name,
                kind="top-level-dag",
                stable_node_ids=tuple(descendants),
                metadata={
                    "maya_names": (node.full_path,),
                    "pre_open_roots": (node.full_path,),
                    "scope": "Maya ASCII top-level DAG",
                },
            )
        )
    for reference in document.references:
        identity = reference.reference_node or reference.path
        candidates.append(
            BisectCandidate(
                id=_ascii_identity("reference", identity),
                label=reference.reference_node or Path(reference.path).name,
                kind="reference",
                metadata={
                    "reference_node": reference.reference_node,
                    "reference_path": reference.path,
                    "pre_open_reference_paths": (reference.path,),
                    "namespace": reference.namespace,
                },
            )
        )
    if not candidates:
        raise RunnerError("No pre-open Maya ASCII Bisect candidates were found")
    candidates.sort(key=lambda item: (item.kind, item.label, item.id))
    return BisectPlan(
        source_scene=str(source),
        source_sha256=sha256_file(source),
        candidates=tuple(candidates),
        maya_executable=str(Path(maya_executable).expanduser().resolve()),
        timeout_seconds=timeout_seconds,
        metadata={
            "isolation_mode": "pre-open-ascii",
            "capability": "pre-open Maya ASCII DAG/reference isolation",
            "source_statement_count": len(document.statements),
            "source_node_count": len(document.nodes),
            "source_reference_count": len(document.references),
        },
    )
