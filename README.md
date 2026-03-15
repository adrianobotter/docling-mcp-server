# EVIE MCP Server

**Evidence Intelligence & Context Infrastructure**

Governed clinical evidence for verified healthcare professionals (HCPs) via the Claude.ai Connector. EVIE is a thin query layer over Supabase — no PDF processing, no ML.

## Architecture

```
Admin App ──WRITE──▶ Supabase ◀──READ── EVIE MCP Server ──▶ Claude.ai Connector
```

- **Admin App** — pharma teams ingest evidence, assign governance
- **Supabase** — shared database with Row-Level Security
- **EVIE MCP Server** (this repo) — HCPs query governed evidence through Claude

## MCP Tools

| Tool | Description |
|------|-------------|
| `list_trials` | List clinical trials available to the authenticated HCP |
| `get_trial_summary` | Get primary endpoint overview with Context Envelopes |
| `get_evidence` | Full-text search across clinical evidence |
| `get_evidence_detail` | Get complete evidence object with full context envelope |
| `get_safety_data` | Get adverse event data for a trial |

Every tool response includes a **Context Envelope** with population constraints, interpretation guardrails, and a mandatory safety statement.

## Setup

### 1. Environment variables

Copy the example and fill in your Supabase credentials:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Your Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Supabase anonymous/public API key |
| `EVIE_BASE_URL` | No | Public URL of this server (defaults to Railway domain) |
| `PORT` | No | Server port (default: 8000) |
| `HOST` | No | Bind address (default: 0.0.0.0) |

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the database migrations

Apply the schema, RLS policies, and seed data to your Supabase project:

```bash
# In the Supabase SQL Editor, run in order:
# migrations/001_schema.sql
# migrations/002_rls.sql
# migrations/003_seed_step4.sql
```

### 4. Run locally

```bash
python -m src.evie.server
```

Server starts at `http://localhost:8000`. Health check at `/health`.

## Deploy to Railway

The repo includes `Dockerfile` and `railway.toml` for one-click Railway deployment.

Set these environment variables in Railway:
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `EVIE_BASE_URL` (set to your Railway public domain)

## Authentication

EVIE enforces three layers of security:

| Layer | Mechanism |
|-------|-----------|
| **1 — Connector Auth** | OAuth 2.0 flow via Claude.ai Connector |
| **2 — Database RLS** | Supabase Row-Level Security filters by tier + published status |
| **3 — Tool-level check** | Each tool verifies `verification_status = 'verified'` |

## Claude.ai Connector Setup

HCPs activate the EVIE Connector in Claude.ai Settings → Connectors → Add Custom Connector:

| Field | Value |
|-------|-------|
| Connector URL | `https://<your-domain>/mcp` |
| Auth type | OAuth 2.0 |

## Project Structure

```
src/evie/
├── server.py    # FastMCP server setup, routes, entry point
├── tools.py     # 5 MCP tool definitions
├── db.py        # Supabase client and query helpers
├── oauth.py     # OAuth Authorization Server (wraps Supabase Auth)
├── auth.py      # HCP profile verification (Layer 3)
├── models.py    # Pydantic models for evidence and envelopes
└── _state.py    # Shared state (avoids circular imports)

migrations/
├── 001_schema.sql       # Tables, indexes, triggers
├── 002_rls.sql          # Row-Level Security policies
└── 003_seed_step4.sql   # Seed data (STEP-4 trial)

docs/
└── architecture.md      # Full architecture documentation
```

## License

Private — all rights reserved.
