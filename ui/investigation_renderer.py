"""PySide-side renderer for host-independent investigation intentions."""

from __future__ import annotations

from ..application import (
    AtlasClearIntent,
    AtlasCounterfactualIntent,
    AtlasDeltaIntent,
    AtlasHighlightIntent,
    AtlasLensIntent,
    AtlasPulseIntent,
    AtlasSceneIntent,
    AtlasSelectionIntent,
    InvestigationTransition,
)


def render_atlas_transition(atlas, transition: InvestigationTransition) -> None:
    """Dispatch typed application intentions to the production Atlas view."""
    for intent in transition.atlas_intents:
        if isinstance(intent, AtlasSceneIntent):
            atlas.set_snapshot(
                intent.snapshot,
                intent.issues,
                priority_node_ids=intent.priority_node_ids,
            )
        elif isinstance(intent, AtlasHighlightIntent):
            atlas.highlight(intent.node_ids)
        elif isinstance(intent, AtlasLensIntent):
            atlas.show_lens(intent.report, intent.candidate)
        elif isinstance(intent, AtlasSelectionIntent):
            atlas.select_node_ids(intent.node_ids, center=intent.center)
        elif isinstance(intent, AtlasPulseIntent):
            atlas.show_pulse(intent.stats)
        elif isinstance(intent, AtlasCounterfactualIntent):
            atlas.show_counterfactual(intent.report)
        elif isinstance(intent, AtlasDeltaIntent):
            atlas.show_delta(intent.delta)
        elif isinstance(intent, AtlasClearIntent):
            atlas.clear_lens()
        else:
            raise TypeError("未知 Atlas 渲染意图：%s" % type(intent).__name__)


__all__ = ["render_atlas_transition"]
