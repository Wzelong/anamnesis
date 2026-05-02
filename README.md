# Anamnesis

Healthcare AI agent for the Prompt Opinion "Agents Assemble" hackathon. Extracts structured history from clinical notes, diffs it against the existing FHIR chart, and surfaces augmentations through an MCP server.

## Architecture

- **Backend** (`backend/`): FastAPI + FastMCP. Serves the MCP interface to Prompt Opinion and a REST API to the frontend.
- **MCP tools**: Read SHARP context (FHIR URL + bearer token) from per-request headers, call the Prompt Opinion FHIR server, return results.
- **Transport**: Streamable HTTP, mounted at `/mcp`.

## Local run

Prereqs: Python 3.11+, an ngrok account (free tier), a Prompt Opinion workspace.

Three terminals.

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate             # Windows
# source .venv/bin/activate        # macOS/Linux
pip install -e ".[dev]"
cp .env.example .env               # then fill values
uvicorn main:app --reload --port 8042
```

Sanity check: `curl http://localhost:8042/health` → `{"status":"ok","service":"anamnesis"}`.

### 2. ngrok tunnel

Our reserved static domain: **`ogle-spinach-splendor.ngrok-free.dev`**

```bash
ngrok http --domain=ogle-spinach-splendor.ngrok-free.dev 8042
```

Public MCP URL: `https://ogle-spinach-splendor.ngrok-free.dev/mcp`

Inspector (every request Prompt Opinion makes): http://127.0.0.1:4040

### 3. Prompt Opinion registration

One-time setup in Workspace Hub → Add MCP Server:

- **URL**: `https://ogle-spinach-splendor.ngrok-free.dev/mcp`
- **Transport**: Streamable HTTP
- **Authentication**: None (dev)
- **Pass FHIR context**: checked (sends SHARP headers)
- Click **Test** → confirms tools list
- Save

Then build a custom agent: **Agents → Build your own**, context type **Patient**, include this MCP's tools, and invoke from Launchpad.

## Repo layout

```
backend/
  main.py              # FastAPI app + MCP mount
  config.py            # pydantic-settings
  api/                 # REST surface for frontend
  mcp_server/          # FastMCP instance + tools
  context/sharp.py     # SHARP header extraction
  fhir/client.py       # async FHIR client
  core/                # extraction, diff, augment, classifier (stubs)
  db/                  # SQLAlchemy models + session
  tests/               # pytest smoke tests
```

## Useful links

- Hackathon page: https://healthcareagents.devpost.com
- SHARP-on-MCP spec: https://sharponmcp.com
- Reference MCP: https://github.com/darena-solutions/darena-health-community-mcp
- Getting-started video: https://youtu.be/Qvs_QK4meHc
