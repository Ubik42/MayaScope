"""Host-independent presentation state for MayaScope workspaces."""

from .evidence import ClinicEvidencePresenter, EvidencePanelState
from .workspace import WorkspacePresentationState
from .project_gate import (
    ProjectGatePresentationError,
    ProjectGateSceneState,
    ProjectGateViewState,
    empty_project_gate,
    present_project_fault,
    present_project_queue,
    present_project_report,
)
from .lens import (
    LensCandidateCardState,
    LensCandidateEvidenceState,
    LensPresentationError,
    LensResultState,
    present_lens_candidate,
    present_lens_result,
)
from .atlas_window import (
    AtlasEdgeKey,
    AtlasNodePlacement,
    AtlasWindowDiff,
    AtlasWindowPlan,
    build_atlas_window,
    diff_atlas_windows,
)
from .bisect import (
    BisectPrismState,
    begin_bisect_prism,
    fail_bisect_prism,
    finish_bisect_prism,
    present_bisect_attempt,
    request_bisect_cancel,
)

__all__ = [
    "ClinicEvidencePresenter",
    "EvidencePanelState",
    "WorkspacePresentationState",
    "ProjectGatePresentationError",
    "ProjectGateSceneState",
    "ProjectGateViewState",
    "empty_project_gate",
    "present_project_fault",
    "present_project_queue",
    "present_project_report",
    "LensCandidateCardState",
    "LensCandidateEvidenceState",
    "LensPresentationError",
    "LensResultState",
    "present_lens_candidate",
    "present_lens_result",
    "AtlasEdgeKey",
    "AtlasNodePlacement",
    "AtlasWindowDiff",
    "AtlasWindowPlan",
    "build_atlas_window",
    "diff_atlas_windows",
    "BisectPrismState",
    "begin_bisect_prism",
    "fail_bisect_prism",
    "finish_bisect_prism",
    "present_bisect_attempt",
    "request_bisect_cancel",
]
