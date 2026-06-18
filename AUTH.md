# Authentication & Authorization

How Anamnesis authenticates clinicians, what the Prompt Opinion (PO) token
carries, where the current design sits relative to the MCP authorization spec,
and what is required before storing per-user secrets. Findings as of 2026-06-18.

## Context: Anamnesis is a resource server behind Prompt Opinion

Anamnesis is an MCP server published to the PO marketplace. **PO is the host and
the authorization server.** A clinician adds the MCP inside PO; PO runs the OAuth
flow, authenticates the clinician, and mints an access token. PO then calls our
MCP endpoint per request, propagating launch context as SHARP HTTP headers:

| Header | Contents |
|---|---|
| `x-fhir-server-url` | the patient's FHIR base (`.../api/workspaces/<ws>/fhir`) |
| `x-fhir-access-token` | the PO-issued JWT (bearer for FHIR + identity claims) |
| `x-patient-id` | the patient in context |

We mint no tokens and store no tokens. Identity is a pure function of the
per-request JWT.

## The PO access token (captured from a live session)

Decoded claims (non-PHI fields shown; capture via `context/debug_token.py`,
env-gated by `DEBUG_TOKEN_CLAIMS`):

| Claim | Value / meaning |
|---|---|
| `sub` | clinician's stable OIDC subject (UUID) — **the per-user identity key** |
| `is_client_creds` | `false` — a real user token, not a client-credentials grant |
| `role` | `User` |
| `client_id` | `po-default` — a generic shared client (not per-clinician) |
| `po_ws_id` | the PO workspace / tenant id |
| `po_mcp_id` | the MCP app instance id |
| `given_name` / `family_name` | clinician display name (granted by the `profile` scope) |
| `scope` | `openid profile po_fhir user/*.cruds` |
| `iss` | `https://app.promptopinion.ai/` |
| `jti` / `oi_tkn_id` | per-token ids (do **not** key on these) |
| `aud` | **absent** |

Key conclusions:

- **`sub` is the clinician.** `is_client_creds=false` + `role=User` + the `user/`
  scope + per-user `given_name`/`family_name` confirm a user token, so `sub`
  identifies the clinician (not a shared service principal). There is **no
  `fhirUser` claim**, so `sub` is the identity we key on.
- **`po_ws_id` is the workspace/tenant** — stored as a secondary grouping key
  (and the natural unit for future workspace-level config / BYOK billing).
- **No `aud` claim** — see the audience-binding gap below.

## MCP authorization spec (2025-11-25) — and what applies to us

The spec models a protected MCP server as an **OAuth 2.1 resource server** with
three pillars:

1. **Discovery** — RFC 9728 Protected Resource Metadata: an unauthenticated
   request returns `401` + `WWW-Authenticate` pointing at
   `/.well-known/oauth-protected-resource`, which names the authorization server.
2. **Client registration** — the 2025-11 shift: **Client ID Metadata Documents
   (CIMD)** are replacing Dynamic Client Registration (DCR). `client_id` becomes
   an HTTPS URL to a JSON metadata document. Priority: pre-registered → CIMD →
   DCR → manual.
3. **Token validation** — verify the JWT locally via JWKS (signature, `iss`,
   `exp`, `aud`), bound to the server with RFC 8707 Resource Indicators. Audience
   validation is mandatory; token passthrough is forbidden (confused deputy).
   PKCE is mandatory client-side.

**Only pillar 3 is ours.** PO owns discovery, client registration (CIMD/DCR),
PKCE, redirect URIs, and consent. We do not run a PRM endpoint or register
clients. Our slice of the spec is: *verify the token PO hands us, as a pure
resource server.*

## Current state

Identity is read with `jwt.decode(token, options={"verify_signature": False})`
(`context/auth.py`). This is **host-delegated trust**: we trust that PO issued
the token because PO is the only caller in front of us.

- **Works today.** `ReviewChart` decodes `sub`, upserts `app_user`, loads config;
  per-clinician config persists and the same clinician is recognized across
  sessions (`seen_count` increments).
- **Acceptable for non-secret config.** A forged token would still fail every
  FHIR operation (the FHIR server rejects it), so PHI is self-protecting.
- **Known gap:** `/mcp` is public and ungated. A forged `x-fhir-access-token`
  claiming an arbitrary `sub` could read/overwrite *that sub's* non-secret
  config. Low severity now (config is prompt/IG/coding preferences, no secrets);
  **serious once BYOK API keys are stored.**

## Verification is feasible now (verified live)

PO exposes the discovery + key material required to verify tokens:

- OIDC discovery: `https://app.promptopinion.ai/.well-known/openid-configuration`
- `issuer`: `https://app.promptopinion.ai/`
- `jwks_uri`: `https://app.promptopinion.ai/.well-known/jwks` — serves **one RSA
  RS256 signing key** (`use=sig`, `kid 4EB6D54B...`)

So a `verify_po_token()` that checks **signature + `iss` + `exp`** against the
cached JWKS is implementable today. Two caveats specific to PO:

- **No `aud` claim**, so strict audience validation (the spec's MUST) is not
  possible as-is. Mitigations: ask PO to add `aud` / honor the `resource`
  parameter; or assert `po_mcp_id` equals our app instance as a pseudo-audience;
  or accept signature+`iss`+`exp` (weaker, but proves PO issued the token).
- **Verify manually.** FastMCP's built-in `JWTVerifier` (`auth=`) reads the
  `Authorization: Bearer` header, but PO sends the token in `x-fhir-access-token`.
  So verification belongs in our token-reading path (PyJWT + `PyJWKClient`,
  JWKS cached), not the framework's auth gate.

## Trust tiers (the design)

| Operation | Trust model |
|---|---|
| Read FHIR context (patient, notes) — PHI passthrough | host-delegated (unverified decode OK; the token self-fails at FHIR if forged) |
| Read/write non-secret config (`Get/SetUserConfig`) | host-delegated today; verify before relying on it for anything sensitive |
| Read/write **secrets** (BYOK API keys) | **must verify** the token (JWKS signature + `iss` + `exp`) — keying a secret to an unverified `sub` is privilege escalation |

A token used at the FHIR server is **not** forbidden passthrough: PO mints it
with `po_fhir` + `user/*.cruds` scope specifically for FHIR access. That is PO's
designed shared-token model, not a token meant for us being forwarded to an
unrelated third party.

## Persisted state

The only persisted table is `app_user`, keyed on `sub`
(`db/models.py`, `services/users.py`): `display_name`, `workspace_id`, `role`,
`config` (JSONB framework knobs), `seen_count`, timestamps. Clinician identity is
not patient PHI; config is configuration. No PHI is persisted.

## Next steps

1. **Done.** `verify_po_token()` (`context/token_verify.py`) verifies JWKS
   signature + `iss` + `exp` via a cached `PyJWKClient`, with an optional
   `po_mcp_id` pseudo-audience check. Both `GetUserConfig` and `SetUserConfig`
   are gated behind it (`prefab_verified_user_context`), closing the
   forge-config hole on the read and write sides. Toggle with
   `verify_config_writes`; gate future secret tools the same way.

   **Gating rule:** gate anything that reads or writes per-`sub` state that is
   not independently enforced elsewhere (config, future secrets). Leave FHIR
   passthrough (`ReviewChart` patient read, `RunExtraction`, `AcceptAugmentation`)
   host-delegated — the FHIR server is the enforcement point, so a forged token
   self-fails there and a verification gate would be redundant (and would couple
   the whole demo's availability to JWKS reachability).
2. **Audience:** raise the missing `aud` claim with PO (or adopt the `po_mcp_id`
   pseudo-audience check) so verification can bind to this resource.
3. **BYOK secrets — done.** `core/byok.py` Fernet-encrypts secret fields
   (`openai_api_key`, `umls_api_key`) at rest under `CONFIG_SECRET_KEY`, decrypts
   in-process only (pipeline use), and redacts to `{set, last4}` on read so
   plaintext never reaches the iframe. Gated behind (1). Remaining: key rotation
   / re-encryption tooling.
