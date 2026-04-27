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
