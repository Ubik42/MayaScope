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
]
