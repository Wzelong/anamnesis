# Security Policy

Anamnesis operates on clinical data and writes to FHIR servers. Security is a first-class concern.

## Reporting a vulnerability

Do not open a public issue for security vulnerabilities.

Report privately via [GitHub Security Advisories](https://github.com/Wzelong/anamnesis/security/advisories/new), or email **zelongw@usc.edu** with subject `SECURITY: Anamnesis`.

Please include:

- A description of the issue and its impact
- Steps to reproduce or a proof of concept
- Affected component (backend pipeline, MCP surface, review app, FHIR write path, auth/BYOK)

We aim to acknowledge within 3 business days and to provide a remediation timeline after triage. Please allow a reasonable disclosure window before publishing details.

## Security posture

These are design invariants, not aspirations. A regression in any of them is a security bug.

- **No PHI at rest.** The pipeline runs in memory. Extracted clinical data never touches disk. The only persisted state is per-clinician config and a non-PHI usage ledger (token/cost metadata, no patient id, no clinical content).
- **BYOK, encrypted at rest.** Secret fields (`gemini_api_key`, `umls_api_key`) are Fernet-encrypted under `CONFIG_SECRET_KEY`, decrypted in-process only, and redacted to `{set, last4}` before leaving the server. Plaintext keys never reach the client.
- **Per-user writes are signature-verified.** Any write keyed to a clinician identity (`sub`) requires a Prompt Opinion token whose JWKS signature, issuer, and expiry are verified server-side (`context/token_verify.py`). Read paths stay host-delegated: a forged token self-fails at the FHIR server.
- **Nothing writes to FHIR silently.** Every chart change passes through `apply_augmentation` and is paired with a `Provenance` resource. Inline source text enters the chart only when its derived augmentation is accepted, in the same transaction.

## Handling secrets

- Never commit real secrets. `backend/.env` is gitignored; use `backend/.env.example` as a template.
- `CONFIG_SECRET_KEY`, `GEMINI_API_KEY`, `UMLS_API_KEY`, and `DATABASE_URL` are provided via environment in deployment, never checked in.
- If you believe a secret was committed, rotate it immediately and report per the process above.

## Scope

In scope: the backend server, MCP tool surface, auth/token verification, BYOK encryption, and the FHIR write path. Out of scope: vulnerabilities in third-party FHIR servers, the Prompt Opinion host, or upstream terminology services (UMLS/RxNav/NLM).
