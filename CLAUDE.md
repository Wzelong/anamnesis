# Anamnesis

## What this project is

Anamnesis is a hackathon submission for the **Agents Assemble: The Healthcare AI Endgame** challenge, hosted on the Prompt Opinion platform.

The submission is a **FHIR augmentation agent**: it reads clinical notes against an existing FHIR record, proposes additions and corrections with full source provenance, and writes them back to the FHIR server after a clinician approves them.

The thesis is summarized as: *the data wasn't missing — it was unstructured. Now it's not.*

The product is delivered primarily as an **MCP server** published to the Prompt Opinion Marketplace, with a thin **A2A agent wrapper** (configured inside Prompt Opinion) and a **provider-facing review workspace** that serves as the human-in-the-loop hand-off surface.

The name comes from the medical term for a patient history reconstructed from documentation — which is what the agent does.

## Who the user is

The demo persona is a **provider doing pre-visit chart catch-up** across multi-source clinical notes (cardiology consult, external ER visit, neurology follow-up). The underlying capability is general — any agent in the Prompt Opinion ecosystem can compose the MCP — but the demo speaks to clinicians.

This is **not** a payer tool, not a patient app, not an EHR replacement, and not an ambient-capture product.

## Core principles

- **Structure first, reason second, act third.** Augmentation precedes insight.
- **Every fact carries provenance.** Source span, extraction reasoning, confidence, approver — all auditable.
- **Nothing writes silently.** Human approval is required before any FHIR write.
- **The MCP is the real product.** The frontend is a reference consumer, not the differentiator.
- **FHIR is the source of truth.** Clinical data lives on the Prompt Opinion FHIR server. The local DB only holds working state (proposals, decisions, audit log).

## Repository structure

This repo contains two top-level folders. They are independently runnable but share a common contract: the frontend calls the backend; the backend calls the FHIR server.

### `/backend`

The MCP server and augmentation engine. This is the substantive deliverable.

Responsibilities:
- Expose MCP tools for proposing, retrieving, accepting, and rejecting FHIR augmentations
- Pull existing FHIR resources and clinical documents from the Prompt Opinion FHIR server using SHARP-propagated tokens
- Run extraction over clinical notes and classify candidate resources against the existing record
- Persist proposals and decisions in working-state storage
- Write accepted augmentations back to FHIR with proper `Provenance` resources
- Be invokable by any agent in the Prompt Opinion ecosystem — not just our frontend

The backend should remain **complete on its own**. A different consumer (another team's agent, a different UI, a CLI) should be able to use the MCP without the frontend existing.

### `/mcp-app`

The provider-facing review workspace, delivered as an **MCP App** (Vite + React) that the backend serves and the Prompt Opinion host renders in an iframe. The deep-linkable, human-in-the-loop surface that makes auditability visible.

Responsibilities:
- Open from the host with patient context already in scope (no separate login)
- Render the patient header, source notes, and the augmentation review queue
- For each proposal, show: source span highlighted in the original note, extracted FHIR resource, classification, confidence, and conflicts with existing FHIR
- Accept / reject / edit actions that call backend MCP tools
- Display the FHIR write outcome with the generated Provenance resource visible

Build with `npm run build` in `mcp-app/`; the bundle is emitted into `backend/mcp_server/ui/assets/` (committed, since Render serves it with no cloud Node build).

The frontend should remain a **thin client**. It calls the backend for everything. No business logic, no parallel data store, no augmentation reasoning. If a feature feels like it wants logic in the frontend, that logic likely belongs in the backend.

## Conventions

- Keep code readable over clever. The reviewer audience includes clinical informaticists, not just engineers.
- FHIR resources should validate against R4 and conform to US Core where applicable.
- Use existing, well-known libraries for FHIR interaction; do not hand-roll resource validation.
- Log every tool call with structured input/output. Logs are useful for both demo recording and post-mortem debugging.

## When in doubt

If a design decision isn't covered here:
1. Default to keeping the backend self-sufficient and the frontend thin.
2. Default to making provenance more visible, not less.
3. Default to scope discipline — additions to the demo path need a clear reason; additions outside the demo path probably don't belong in this hackathon submission at all.
4. If the choice affects the demo's clinical realism, flag it for human review rather than guessing.