"""Shared mutable state — avoids circular imports between server and tools."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .oauth import SupabaseOAuthProvider

oauth_provider: SupabaseOAuthProvider | None = None
