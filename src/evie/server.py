"""
EVIE MCP Server
Governed clinical evidence for HCPs via Claude.ai Connector.

Thin query layer over Supabase — no PDF processing, no ML, no Docling.
"""

import os

from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import _state
from .oauth import SupabaseOAuthProvider
from .tools import register_tools


# ─── Bearer token middleware ─────────────────────────────────────────────────

# Paths that skip bearer token validation
_PUBLIC_PATHS = {"/health"}


class BearerTokenMiddleware:
    """Validate MCP_BEARER_TOKEN on all requests except health checks."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        # Extract Authorization header
        headers = dict(scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode()

        if not auth_value.startswith("Bearer ") or auth_value[7:] != self.token:
            response = JSONResponse(
                {"error": "Unauthorized", "detail": "Valid Bearer token required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# ─── Auth (Supabase as identity backend) ─────────────────────────────────────


def _create_auth() -> SupabaseOAuthProvider | None:
    """Create OAuth provider that acts as an AS, delegating to Supabase.

    Unlike RemoteAuthProvider, this serves the full OAuth AS endpoints
    (/.well-known/oauth-authorization-server, /authorize, /token, /register)
    so Claude.ai Connector can complete RFC 8414 discovery.
    """
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_anon_key:
        return None

    base_url = os.environ.get("EVIE_BASE_URL", "https://evie-mcp.railway.app")

    provider = SupabaseOAuthProvider(
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key,
        base_url=base_url,
    )
    _state.oauth_provider = provider
    return provider


# ─── Server setup ─────────────────────────────────────────────────────────────

mcp = FastMCP(
    "evie",
    instructions=(
        "EVIE provides governed clinical evidence from published trials. "
        "Every evidence result includes a Context Envelope with population constraints, "
        "interpretation guardrails, and a safety statement. Always present these "
        "guardrails to the user — never omit or summarize away the safety statement. "
        "Start with list_trials to see available data, then use get_trial_summary, "
        "get_evidence, get_evidence_detail, or get_safety_data as needed."
    ),
    auth=_create_auth(),
)

# Register all 5 evidence tools
register_tools(mcp)


# ─── Health check ─────────────────────────────────────────────────────────────

@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    return JSONResponse({"status": "ok", "server": "evie_mcp"})


# ─── OAuth callback from Supabase ────────────────────────────────────────────

@mcp.custom_route("/oauth/callback", methods=["GET"])
async def oauth_callback(request):
    """Handle redirect from Supabase after user authenticates.

    Supabase redirects here with either an authorization code or tokens.
    We exchange them and redirect back to Claude.ai with our own auth code.
    """
    provider = _state.oauth_provider
    if not provider:
        return JSONResponse({"error": "Auth not configured"}, status_code=500)

    params = request.query_params
    code = params.get("code")
    state = params.get("state")
    access_token = params.get("access_token")
    refresh_token = params.get("refresh_token")

    try:
        redirect_url = await provider.handle_supabase_callback(
            code=code,
            state=state,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        return RedirectResponse(redirect_url)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ─── Well-known MCP server card ──────────────────────────────────────────────

@mcp.custom_route("/.well-known/mcp.json", methods=["GET"])
async def mcp_server_card(request):
    return JSONResponse({
        "name": "EVIE — Clinical Evidence",
        "description": (
            "Access governed clinical trial evidence with mandatory context envelopes. "
            "Every result includes population constraints, interpretation guardrails, "
            "and safety statements."
        ),
        "auth": {"type": "oauth2"},
        "tools": [
            {
                "name": "list_trials",
                "description": "List clinical trials available to you",
            },
            {
                "name": "get_trial_summary",
                "description": "Get primary endpoint overview for a trial",
            },
            {
                "name": "get_evidence",
                "description": "Search clinical evidence with natural language",
            },
            {
                "name": "get_evidence_detail",
                "description": "Get full evidence object with context envelope",
            },
            {
                "name": "get_safety_data",
                "description": "Get adverse event data for a trial",
            },
        ],
    })


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    """Run the Evie MCP Server with Streamable HTTP transport."""
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    # Validate required env vars
    required = ["SUPABASE_URL", "SUPABASE_ANON_KEY"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    app = mcp.http_app()

    # Wrap with bearer token auth if MCP_BEARER_TOKEN is set
    bearer_token = os.environ.get("MCP_BEARER_TOKEN")
    if bearer_token:
        app = BearerTokenMiddleware(app, bearer_token)

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
