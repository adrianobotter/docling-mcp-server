"""Tests for EVIE HCP authentication and verification (Layer 3)."""

from unittest.mock import patch, MagicMock
import pytest

from src.evie.auth import AuthError, AuthenticatedHCP, verify_hcp


class TestAuthError:
    def test_error_attributes(self):
        err = AuthError("test message", code="test_code")
        assert err.message == "test message"
        assert err.code == "test_code"
        assert str(err) == "test message"

    def test_default_code(self):
        err = AuthError("msg")
        assert err.code == "auth_error"


class TestAuthenticatedHCP:
    def test_dataclass_fields(self, sample_hcp_row):
        from src.evie.models import HCPProfile
        profile = HCPProfile(**sample_hcp_row)
        hcp = AuthenticatedHCP(
            user_id="user-123",
            access_token="tok-abc",
            profile=profile,
        )
        assert hcp.user_id == "user-123"
        assert hcp.access_token == "tok-abc"
        assert hcp.profile.verification_status == "verified"


class TestVerifyHCP:
    @pytest.mark.asyncio
    async def test_invalid_token_raises(self):
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = None

        with patch("src.evie.auth.create_client", return_value=mock_client):
            with pytest.raises(AuthError, match="Invalid or expired"):
                await verify_hcp("bad-token")

    @pytest.mark.asyncio
    async def test_no_profile_raises(self):
        mock_user = MagicMock()
        mock_user.user.id = "user-123"

        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = mock_user
        mock_client.auth.set_session.return_value = None

        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.evie.auth.create_client", return_value=mock_client):
            with pytest.raises(AuthError, match="No HCP profile"):
                await verify_hcp("valid-token")

    @pytest.mark.asyncio
    async def test_unverified_raises(self, sample_hcp_row):
        sample_hcp_row["verification_status"] = "pending"

        mock_user = MagicMock()
        mock_user.user.id = "user-123"

        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = mock_user
        mock_client.auth.set_session.return_value = None

        mock_result = MagicMock()
        mock_result.data = [sample_hcp_row]
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.evie.auth.create_client", return_value=mock_client):
            with pytest.raises(AuthError, match="verification status is 'pending'"):
                await verify_hcp("valid-token")

    @pytest.mark.asyncio
    async def test_verified_succeeds(self, sample_hcp_row):
        mock_user = MagicMock()
        mock_user.user.id = "user-123"

        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = mock_user
        mock_client.auth.set_session.return_value = None

        mock_result = MagicMock()
        mock_result.data = [sample_hcp_row]
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_result

        with patch("src.evie.auth.create_client", return_value=mock_client):
            hcp = await verify_hcp("valid-token")
            assert isinstance(hcp, AuthenticatedHCP)
            assert hcp.profile.verification_status == "verified"
            assert hcp.user_id == "user-123"
