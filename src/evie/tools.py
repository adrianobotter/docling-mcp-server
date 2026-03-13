"""EVIE MCP Tool definitions — 5 governed clinical evidence tools for HCPs."""

import json
from typing import Optional

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.auth import AccessToken

from . import db
from .auth import AuthError, verify_hcp
from . import _state


def _error_response(message: str, code: str = "error") -> str:
    return json.dumps({"error": code, "message": message})


async def _authenticate(access_token: AccessToken | None):
    """Verify the HCP from the FastMCP-injected access token.

    The access token from FastMCP is an EVIE-issued token. We look up the
    corresponding Supabase token to verify the HCP profile.
    """
    if not access_token:
        raise AuthError("No access token found. Please authenticate via the Evie Connector.", code="no_token")

    # Resolve the Supabase token from the EVIE token
    provider = _state.oauth_provider
    if provider:
        supabase_token = provider.get_supabase_token(access_token.token)
        if not supabase_token:
            raise AuthError("Invalid or expired access token.", code="invalid_token")
        return await verify_hcp(supabase_token)

    # Fallback: use the token directly (no OAuth provider configured)
    return await verify_hcp(access_token.token)


def register_tools(mcp: FastMCP) -> None:
    """Register all Evie tools on the given FastMCP server."""

    @mcp.tool(
        name="list_trials",
        annotations={
            "title": "List Available Trials",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def list_trials() -> str:
        """List clinical trials available to you based on your verification status and access tier.

        Returns a JSON array of trials you can query, including trial name, drug,
        indication, phase, and available evidence types.
        """
        try:
            access_token = get_access_token()
            hcp = await _authenticate(access_token)
        except AuthError as e:
            return _error_response(e.message, e.code)

        client = db.get_client(access_token=hcp.access_token)
        trials = db.list_trials(client)
        return json.dumps([t.model_dump() for t in trials], indent=2)

    @mcp.tool(
        name="get_trial_summary",
        annotations={
            "title": "Get Trial Summary",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_trial_summary(trial_id: str) -> str:
        """Get a structured overview of a specific clinical trial.

        Returns trial metadata and primary endpoint evidence objects with full
        Context Envelopes (population constraints, guardrails, safety statements).
        Use dedicated tools for subgroup, safety, or comparator data.

        Args:
            trial_id: UUID of the trial to summarize.
        """
        try:
            access_token = get_access_token()
            hcp = await _authenticate(access_token)
        except AuthError as e:
            return _error_response(e.message, e.code)

        client = db.get_client(access_token=hcp.access_token)
        summary = db.get_trial_summary(client, trial_id)
        if not summary:
            return _error_response("Trial not found or not accessible.", "not_found")
        return json.dumps(summary, indent=2)

    @mcp.tool(
        name="get_evidence",
        annotations={
            "title": "Search Clinical Evidence",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_evidence(
        query: str,
        trial_id: Optional[str] = None,
        object_class: Optional[str] = None,
    ) -> str:
        """Search across clinical evidence using natural language.

        Returns matching evidence objects with complete Context Envelopes including
        population constraints, interpretation guardrails, and safety statements.

        Args:
            query: Natural language search — e.g. 'weight loss in patients with BMI > 35'.
            trial_id: Optional UUID to scope search to a specific trial.
            object_class: Optional filter — 'primary_endpoint', 'subgroup', 'adverse_event', or 'comparator'.
        """
        try:
            access_token = get_access_token()
            hcp = await _authenticate(access_token)
        except AuthError as e:
            return _error_response(e.message, e.code)

        client = db.get_client(access_token=hcp.access_token)
        results = db.search_evidence(client, query, trial_id=trial_id, object_class=object_class)
        return json.dumps(
            [r.model_dump() for r in results],
            indent=2,
        )

    @mcp.tool(
        name="get_evidence_detail",
        annotations={
            "title": "Get Evidence Detail",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_evidence_detail(evidence_object_id: str) -> str:
        """Get the complete evidence object and its full Context Envelope.

        Returns all fields for a specific evidence result, including population
        constraints, endpoint definition, interpretation guardrails, safety
        statement, and source provenance.

        Args:
            evidence_object_id: UUID of the evidence object.
        """
        try:
            access_token = get_access_token()
            hcp = await _authenticate(access_token)
        except AuthError as e:
            return _error_response(e.message, e.code)

        client = db.get_client(access_token=hcp.access_token)
        detail = db.get_evidence_detail(client, evidence_object_id)
        if not detail:
            return _error_response("Evidence object not found or not accessible.", "not_found")
        return json.dumps(detail.model_dump(), indent=2)

    @mcp.tool(
        name="get_safety_data",
        annotations={
            "title": "Get Safety Data",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def get_safety_data(trial_id: str) -> str:
        """Get all adverse event data for a clinical trial.

        Returns adverse event evidence objects sorted by incidence rate (highest first),
        each with a mandatory safety statement from the Context Envelope.

        Args:
            trial_id: UUID of the trial.
        """
        try:
            access_token = get_access_token()
            hcp = await _authenticate(access_token)
        except AuthError as e:
            return _error_response(e.message, e.code)

        client = db.get_client(access_token=hcp.access_token)
        results = db.get_safety_data(client, trial_id)
        if not results:
            return _error_response(
                "No safety data found for this trial or not accessible.",
                "not_found",
            )
        return json.dumps(
            [r.model_dump() for r in results],
            indent=2,
        )
