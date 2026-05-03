"""Anamnesis MCP server: FastMCP instance with SHARP capability advertisement."""
from mcp.server.fastmcp import FastMCP

from mcp_server import tools

mcp = FastMCP("Anamnesis", stateless_http=True, host="0.0.0.0")

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

mcp.tool(name="WhoIsPatient", description="Returns identifying info for the current patient.")(
    tools.who_is_patient
)

mcp.tool(
    name="GetPatientContext",
    description="Summary of the patient's existing FHIR record: counts of conditions, meds, allergies, observations, family history, procedures, encounters, and documents.",
)(tools.get_patient_context)

mcp.tool(
    name="ProposeAugmentations",
    description="Run the full augmentation pipeline for the current patient. Extracts clinical findings from notes, codes them with standard terminologies, reconciles against the existing chart, and returns a summary of proposals for review. Returns a deep link to the review UI.",
)(tools.propose_augmentations)

mcp.tool(
    name="ProposeAugmentationsFromNotes",
    description=(
        "Run the augmentation pipeline against agent-supplied note text (e.g. an "
        "extracted PDF, pasted outside record, or email). Use this when the clinician's "
        "note is text the agent already has in hand. Source documents are NOT written to "
        "the FHIR chart unless a derived augmentation is accepted; on accept, the source "
        "DocumentReference is bundled into the same transaction as the resource and "
        "Provenance, so the chart only ever contains ratified evidence. Returns a deep "
        "link to the review UI."
    ),
)(tools.propose_augmentations_from_notes)

mcp.tool(
    name="ListProposals",
    description="List all augmentation proposals for the current patient, grouped by confidence tier (ATTENTION, REVIEW, CONFIDENT). Shows classification, resource type, confidence, and flags for each proposal.",
)(tools.list_proposals_tool)

mcp.tool(
    name="AcceptProposal",
    description="Accept a proposal and write the FHIR resource to the patient's chart with provenance. Only works for NEW proposals when a FHIR connection is available.",
)(tools.accept_proposal_tool)

mcp.tool(
    name="RejectProposal",
    description="Reject a proposal with a reason. The proposal is archived and no FHIR write occurs.",
)(tools.reject_proposal_tool)

mcp.tool(
    name="EditProposal",
    description="Edit the FHIR resource of a pending proposal before accepting. Pass the updated resource as a JSON string. Citations and provenance are preserved.",
)(tools.edit_proposal_tool)
