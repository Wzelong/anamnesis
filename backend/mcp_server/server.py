"""Anamnesis MCP server: FastMCP instance with SHARP capability advertisement."""
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from config import settings
from mcp_server import tools

mcp = FastMCP("Anamnesis", stateless_http=True, host="0.0.0.0")

# MCP Apps: the in-host review UI is served as a single-file HTML resource with
# the MCP-App MIME type; tools that should render it carry `_meta.ui.resourceUri`.
MCP_APP_MIME = "text/html;profile=mcp-app"
REVIEW_RESOURCE_URI = "ui://anamnesis/review.html"
_REVIEW_HTML = Path(__file__).parent / "ui" / "review.html"
_REVIEW_PLACEHOLDER = (
    "<!doctype html><html><body style='font:14px system-ui;padding:24px'>"
    "<h3>Anamnesis review app not built</h3>"
    "<p>Run the mcp-app build to generate <code>review.html</code>.</p>"
    "</body></html>"
)

_SCOPES = [
    {"name": "patient/Patient.rs", "required": True},
    {"name": "patient/Condition.rs"},
    {"name": "patient/MedicationStatement.rs"},
    {"name": "patient/MedicationRequest.rs"},
    {"name": "patient/AllergyIntolerance.rs"},
    {"name": "patient/Observation.rs"},
    {"name": "patient/Procedure.rs"},
    {"name": "patient/DocumentReference.rs"},
]

_original_get_capabilities = mcp._mcp_server.get_capabilities


def _patched_get_capabilities(notification_options, experimental_capabilities):
    caps = _original_get_capabilities(notification_options, experimental_capabilities)
    caps.model_extra["extensions"] = {
        "ai.promptopinion/fhir-context": {"scopes": _SCOPES}
    }
    return caps


mcp._mcp_server.get_capabilities = _patched_get_capabilities

# --- Agent-facing surface (model-visible) ------------------------------------

mcp.tool(
    name="GetPatientContext",
    description="Summary of the patient's existing FHIR record: counts of conditions, medications, allergies, observations, family history, procedures, encounters, and documents. Read-only.",
)(tools.get_patient_context)

mcp.tool(
    name="ReviewChart",
    description=(
        "Open the interactive review workspace for the current patient. Extracts structured "
        "facts from the patient's clinical notes, reconciles them against the existing FHIR "
        "chart, and renders an in-host UI where the clinician reads the source notes, inspects "
        "each proposed resource and any conflicts, and accepts or rejects them — accepted "
        "augmentations are written to FHIR with Provenance. Call this whenever the clinician "
        "wants to review, augment, catch up on, or check the chart against the notes."
    ),
    meta={"ui": {"resourceUri": REVIEW_RESOURCE_URI}, "ui/resourceUri": REVIEW_RESOURCE_URI},
)(tools.review_launcher_tool)

mcp.tool(
    name="SearchTerminology",
    description=(
        "Search a medical terminology by free-text query and return top matching codes. "
        "system must be one of: 'snomed' (findings, conditions, procedures), 'rxnorm' "
        "(medications), 'loinc' (labs/observations), or 'icd10' (billing diagnoses). "
        "Returns code, display, score, and rank. Read-only; no FHIR side effects."
    ),
)(tools.search_terminology_tool)

# --- App-only tools (the review UI calls these via callServerTool) -----------
# Not model-visible: the agent opens ReviewChart, the app drives the rest.

mcp.tool(
    name="RunExtraction",
    description="Run the augmentation pipeline and return proposals plus source notes. Streams stage progress; persists nothing.",
    meta={"ui": {"resourceUri": REVIEW_RESOURCE_URI, "visibility": ["app"]}},
)(tools.run_extraction_tool)

mcp.tool(
    name="AcceptAugmentation",
    description="Accept an augmentation and write it to FHIR with Provenance, using the per-request SHARP token. Resolves from the in-session cache (run_id + proposal_id) or the supplied resource JSON.",
    meta={"ui": {"resourceUri": REVIEW_RESOURCE_URI, "visibility": ["app"]}},
)(tools.accept_augmentation_tool)

mcp.tool(
    name="RejectAugmentation",
    description="Record a reject decision (non-PHI audit). The proposal is dropped client-side.",
    meta={"ui": {"resourceUri": REVIEW_RESOURCE_URI, "visibility": ["app"]}},
)(tools.reject_augmentation_tool)

# --- Legacy DB-backed surface (opt-in) ---------------------------------------
# Pre-stateless tools: they persist working state in SQLite and drive the
# standalone web workspace. Off by default; enable for that deployment.
if settings.expose_legacy_tools:
    mcp.tool(name="WhoIsPatient", description="Returns identifying info for the current patient.")(
        tools.who_is_patient
    )
    mcp.tool(
        name="ProposeAugmentations",
        description="Run the full augmentation pipeline for the current patient and return a summary of proposals plus a deep link to the review UI.",
    )(tools.propose_augmentations)
    mcp.tool(
        name="ProposeAugmentationsFromNotes",
        description="Run the augmentation pipeline against agent-supplied note text. Returns a deep link to the review UI.",
    )(tools.propose_augmentations_from_notes)
    mcp.tool(
        name="GetRunStatus",
        description="Check the status and progress of a pipeline run.",
    )(tools.get_run_status)
    mcp.tool(
        name="ListProposals",
        description="List all augmentation proposals for the current patient, grouped by confidence tier.",
    )(tools.list_proposals_tool)
    mcp.tool(
        name="GetProposal",
        description="Return full detail for a single proposal (resource, citations, reasoning, conflicts).",
    )(tools.get_proposal_tool)
    mcp.tool(
        name="AcceptProposal",
        description="Accept a proposal and write the FHIR resource with provenance.",
    )(tools.accept_proposal_tool)
    mcp.tool(
        name="RejectProposal",
        description="Reject a proposal with a reason. No FHIR write occurs.",
    )(tools.reject_proposal_tool)
    mcp.tool(
        name="ReopenProposal",
        description="Reopen a previously rejected proposal, returning it to pending.",
    )(tools.reopen_proposal_tool)
    mcp.tool(
        name="EditProposal",
        description="Edit the FHIR resource of a pending proposal before accepting.",
    )(tools.edit_proposal_tool)


@mcp.resource(
    REVIEW_RESOURCE_URI,
    name="Anamnesis Review",
    mime_type=MCP_APP_MIME,
    meta={"ui": {"prefersBorder": True}},
)
def review_ui() -> str:
    if _REVIEW_HTML.exists():
        return _REVIEW_HTML.read_text(encoding="utf-8")
    return _REVIEW_PLACEHOLDER
