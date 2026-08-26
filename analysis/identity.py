"""Stable, immutable indexes for mapping Maya host identities to snapshots."""

from __future__ import annotations

from types import MappingProxyType
from typing import Callable, Mapping, Optional

from ..model import SceneSnapshot
from .graph import QueryCancelled


def build_host_identity_index(
    snapshot: SceneSnapshot,
    *,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Mapping[str, str]:
    """Map exact unique node names and DAG paths to stable node IDs.

    Ambiguous short names are deliberately omitted.  Construction is intended
    for the Clinic worker; the returned mapping is immutable and safe to hand
    back to the Qt thread.
    """
    result = {}
    ambiguous = set()
    for index, node in enumerate(snapshot.nodes):
        if cancelled and index % 2048 == 0 and cancelled():
            raise QueryCancelled("Host identity indexing cancelled")
        for identity in (node.name,) + tuple(node.dag_paths):
            identity = str(identity)
            if not identity or identity in ambiguous:
                continue
            previous = result.get(identity)
            if previous is None or previous == node.id:
                result[identity] = node.id
                continue
            result.pop(identity, None)
            ambiguous.add(identity)
    if cancelled and cancelled():
        raise QueryCancelled("Host identity indexing cancelled")
    return MappingProxyType(result)
