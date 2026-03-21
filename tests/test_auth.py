"""Tests for app.middleware.auth — API key authentication middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.middleware.auth import APIKeyMiddleware, _is_public


class TestAuthMiddleware:
    def test_public_paths_are_public(self) -> None:
        """Public paths should not require authentication."""
        assert _is_public("/api/health") is True
        assert _is_public("/") is True
        assert _is_public("/trades") is True
        assert _is_public("/analytics") is True
        assert _is_public("/signals") is True
        assert _is_public("/settings") is True
        assert _is_public("/static/css/style.css") is True
        assert _is_public("/asset/NQ=F") is True

    def test_api_paths_not_public(self) -> None:
        """API paths should require authentication."""
        assert _is_public("/api/analyze/NQ=F") is False
        assert _is_public("/api/assets") is False
        assert _is_public("/api/settings") is False

    @pytest.mark.asyncio
    async def test_middleware_skips_when_no_key(self) -> None:
        """If no API key configured, middleware should pass all requests."""
        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="")
        assert middleware.api_key == ""

    @pytest.mark.asyncio
    async def test_middleware_blocks_invalid_key(self) -> None:
        """Invalid API key should result in 401."""
        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="secret-key-123")

        mock_request = MagicMock()
        mock_request.url.path = "/api/assets"
        mock_request.headers = {"X-API-Key": "wrong-key"}
        mock_request.query_params = {}
        mock_request.client.host = "127.0.0.1"

        mock_call_next = AsyncMock()
        response = await middleware.dispatch(mock_request, mock_call_next)

        assert response.status_code == 401
        mock_call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_middleware_passes_valid_key(self) -> None:
        """Valid API key should pass through."""
        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="secret-key-123")

        mock_request = MagicMock()
        mock_request.url.path = "/api/assets"
        mock_request.headers = {"X-API-Key": "secret-key-123"}
        mock_request.query_params = {}

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_middleware_accepts_query_param(self) -> None:
        """API key via query param should also work."""
        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="secret-key-123")

        mock_request = MagicMock()
        mock_request.url.path = "/api/assets"
        mock_request.headers = {}
        mock_request.query_params = {"api_key": "secret-key-123"}

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()

    @pytest.mark.asyncio
    async def test_middleware_skips_public_paths(self) -> None:
        """Public paths should be allowed even without key."""
        mock_app = MagicMock()
        middleware = APIKeyMiddleware(mock_app, api_key="secret-key-123")

        mock_request = MagicMock()
        mock_request.url.path = "/api/health"
        mock_request.headers = {}
        mock_request.query_params = {}

        mock_response = MagicMock()
        mock_call_next = AsyncMock(return_value=mock_response)
        response = await middleware.dispatch(mock_request, mock_call_next)

        mock_call_next.assert_called_once()
