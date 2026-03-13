"""OAuth provider that makes EVIE its own Authorization Server.

Claude.ai Connector requires RFC 8414 OAuth AS Metadata discovery, which
Supabase doesn't support. This provider wraps Supabase auth behind a
standard OAuth AS so the Connector can complete the OAuth flow:

    Claude.ai  ──OAuth──▶  EVIE MCP Server  ──Supabase Auth──▶  Supabase
"""

import hashlib
import os
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
from fastmcp.server.auth import OAuthProvider
from fastmcp.server.auth.auth import ClientRegistrationOptions
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl


@dataclass
class _PendingAuth:
    """Tracks an in-progress authorization flow."""
    client_id: str
    redirect_uri: str
    code_challenge: str
    scopes: list[str] | None
    state: str | None
    supabase_state: str  # state param we send to Supabase
    created_at: float = field(default_factory=time.time)


@dataclass
class _AuthCode:
    """An issued authorization code, not yet exchanged."""
    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    scopes: list[str] | None
    supabase_access_token: str
    supabase_refresh_token: str
    created_at: float = field(default_factory=time.time)


@dataclass
class _IssuedToken:
    """An access token issued by EVIE, wrapping a Supabase token."""
    token: str
    client_id: str
    scopes: list[str] | None
    supabase_access_token: str
    created_at: float = field(default_factory=time.time)
    expires_in: int = 3600


@dataclass
class _IssuedRefresh:
    """A refresh token issued by EVIE."""
    token: str
    client_id: str
    scopes: list[str] | None
    supabase_refresh_token: str
    created_at: float = field(default_factory=time.time)


class SupabaseOAuthProvider(OAuthProvider):
    """OAuth AS that delegates authentication to Supabase.

    The EVIE server becomes its own OAuth AS (serving /.well-known/oauth-authorization-server,
    /authorize, /token, /register). The /authorize endpoint redirects to Supabase's OAuth
    login page. After Supabase authenticates the user, it redirects back to EVIE's callback,
    which completes the MCP OAuth flow.
    """

    def __init__(self, supabase_url: str, supabase_anon_key: str, base_url: str):
        super().__init__(
            base_url=AnyHttpUrl(base_url),
            required_scopes=["evidence:read"],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["evidence:read"],
                default_scopes=["evidence:read"],
            ),
        )
        self.supabase_url = supabase_url.rstrip("/")
        self.supabase_anon_key = supabase_anon_key
        self._base_url_str = base_url.rstrip("/")

        # In-memory stores (sufficient for single-instance Railway deploy)
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._pending: dict[str, _PendingAuth] = {}  # keyed by supabase_state
        self._auth_codes: dict[str, _AuthCode] = {}  # keyed by code
        self._tokens: dict[str, _IssuedToken] = {}  # keyed by token
        self._refreshes: dict[str, _IssuedRefresh] = {}  # keyed by refresh token

    # ── Client Registration (RFC 7591) ───────────────────────────────────────

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        client_id = client_info.client_id or secrets.token_hex(16)
        client_info.client_id = client_id
        client_info.client_secret = secrets.token_hex(32)
        client_info.client_id_issued_at = int(time.time())
        client_info.client_secret_expires_at = 0  # never expires
        self._clients[client_id] = client_info

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    # ── Authorization ────────────────────────────────────────────────────────

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Redirect to Supabase OAuth login.

        We store the MCP authorization params, then redirect the user to
        Supabase's /authorize endpoint. After login, Supabase redirects
        back to our /oauth/callback.
        """
        supabase_state = secrets.token_urlsafe(32)

        self._pending[supabase_state] = _PendingAuth(
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            code_challenge=params.code_challenge,
            scopes=params.scopes,
            state=params.state,
            supabase_state=supabase_state,
        )

        # Redirect to Supabase OAuth
        callback_url = f"{self._base_url_str}/oauth/callback"
        supabase_params = urlencode({
            "provider": "email",  # Supabase email/password as default
            "redirect_to": callback_url,
            "state": supabase_state,
        })
        return f"{self.supabase_url}/auth/v1/authorize?{supabase_params}"

    # ── Callback from Supabase ───────────────────────────────────────────────

    async def handle_supabase_callback(
        self, code: str | None, state: str | None, access_token: str | None,
        refresh_token: str | None,
    ) -> str:
        """Handle the redirect back from Supabase after user authenticates.

        Supabase can return tokens in two ways:
        1. Authorization code flow: returns code in query params
        2. Implicit/PKCE flow: returns tokens in URL fragment (handled client-side)

        Returns the redirect URL to send the user back to Claude.ai.
        """
        pending = self._pending.pop(state, None) if state else None
        if not pending:
            raise ValueError("Invalid or expired OAuth state")

        # If we got a Supabase auth code, exchange it for tokens
        if code and not access_token:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.supabase_url}/auth/v1/token?grant_type=authorization_code",
                    json={"code": code},
                    headers={
                        "apikey": self.supabase_anon_key,
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code != 200:
                    raise ValueError(f"Supabase token exchange failed: {resp.text}")
                token_data = resp.json()
                access_token = token_data["access_token"]
                refresh_token = token_data.get("refresh_token", "")

        if not access_token:
            raise ValueError("No access token received from Supabase")

        # Issue our own authorization code
        evie_code = secrets.token_urlsafe(48)
        self._auth_codes[evie_code] = _AuthCode(
            code=evie_code,
            client_id=pending.client_id,
            redirect_uri=pending.redirect_uri,
            code_challenge=pending.code_challenge,
            scopes=pending.scopes,
            supabase_access_token=access_token,
            supabase_refresh_token=refresh_token or "",
        )

        # Redirect back to Claude.ai with our authorization code
        redirect_params = {"code": evie_code}
        if pending.state:
            redirect_params["state"] = pending.state
        return f"{pending.redirect_uri}?{urlencode(redirect_params)}"

    # ── Authorization Code ───────────────────────────────────────────────────

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> _AuthCode | None:
        ac = self._auth_codes.get(authorization_code)
        if not ac:
            return None
        if ac.client_id != client.client_id:
            return None
        # Expire after 10 minutes
        if time.time() - ac.created_at > 600:
            self._auth_codes.pop(authorization_code, None)
            return None
        return ac

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: _AuthCode
    ) -> OAuthToken:
        # Remove the code (single use)
        self._auth_codes.pop(authorization_code.code, None)

        # Issue EVIE tokens that wrap the Supabase token
        access_tok = secrets.token_urlsafe(48)
        refresh_tok = secrets.token_urlsafe(48)
        expires_in = 3600

        self._tokens[access_tok] = _IssuedToken(
            token=access_tok,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            supabase_access_token=authorization_code.supabase_access_token,
            expires_in=expires_in,
        )
        self._refreshes[refresh_tok] = _IssuedRefresh(
            token=refresh_tok,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            supabase_refresh_token=authorization_code.supabase_refresh_token,
        )

        return OAuthToken(
            access_token=access_tok,
            token_type="Bearer",
            expires_in=expires_in,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
            refresh_token=refresh_tok,
        )

    # ── Token Verification ───────────────────────────────────────────────────

    async def load_access_token(self, token: str) -> _IssuedToken | None:
        issued = self._tokens.get(token)
        if not issued:
            return None
        if time.time() - issued.created_at > issued.expires_in:
            self._tokens.pop(token, None)
            return None
        return issued

    # ── Refresh Token ────────────────────────────────────────────────────────

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> _IssuedRefresh | None:
        issued = self._refreshes.get(refresh_token)
        if not issued or issued.client_id != client.client_id:
            return None
        return issued

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: _IssuedRefresh,
        scopes: list[str],
    ) -> OAuthToken:
        # Remove old refresh token (rotation)
        self._refreshes.pop(refresh_token.token, None)

        # Refresh the Supabase token
        supabase_access = ""
        supabase_refresh = refresh_token.supabase_refresh_token
        if supabase_refresh:
            async with httpx.AsyncClient() as http:
                resp = await http.post(
                    f"{self.supabase_url}/auth/v1/token?grant_type=refresh_token",
                    json={"refresh_token": supabase_refresh},
                    headers={
                        "apikey": self.supabase_anon_key,
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    supabase_access = data["access_token"]
                    supabase_refresh = data.get("refresh_token", supabase_refresh)

        # Issue new EVIE tokens
        new_access = secrets.token_urlsafe(48)
        new_refresh = secrets.token_urlsafe(48)
        expires_in = 3600

        self._tokens[new_access] = _IssuedToken(
            token=new_access,
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
            supabase_access_token=supabase_access,
            expires_in=expires_in,
        )
        self._refreshes[new_refresh] = _IssuedRefresh(
            token=new_refresh,
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
            supabase_refresh_token=supabase_refresh,
        )

        return OAuthToken(
            access_token=new_access,
            token_type="Bearer",
            expires_in=expires_in,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=new_refresh,
        )

    # ── Revocation ───────────────────────────────────────────────────────────

    async def revoke_token(self, token: _IssuedToken | _IssuedRefresh) -> None:
        if isinstance(token, _IssuedToken):
            self._tokens.pop(token.token, None)
        elif isinstance(token, _IssuedRefresh):
            self._refreshes.pop(token.token, None)

    # ── Helper: resolve Supabase token from EVIE token ───────────────────────

    def get_supabase_token(self, evie_token: str) -> str | None:
        """Look up the Supabase access token for a given EVIE access token."""
        issued = self._tokens.get(evie_token)
        return issued.supabase_access_token if issued else None
