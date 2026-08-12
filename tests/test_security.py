from __future__ import annotations

import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import Settings, settings
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.routers.copilot import ChatRequest


def test_cors_wildcard_production():
    """Verify that using a CORS wildcard (*) in production (DEMO_MODE=False) raises a ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(DEMO_MODE=False, CORS_ORIGINS=["*"])
    
    assert "CORS wildcard '*' is prohibited" in str(exc_info.value)


def test_cors_wildcard_demo_allowed():
    """Verify that using a CORS wildcard (*) is allowed when DEMO_MODE=True."""
    s = Settings(DEMO_MODE=True, CORS_ORIGINS=["*"])
    assert s.DEMO_MODE is True
    assert "*" in s.CORS_ORIGINS


def test_copilot_chat_request_sanitization():
    """Verify that Copilot ChatRequest message input is properly sanitized."""
    # Test HTML stripping
    req = ChatRequest(
        message="Hello <script>alert(1)</script> world!",
        event_id="kerala_2018",
        disaster_type="flood"
    )
    assert req.message == "Hello alert(1) world!"

    # Test control character removal
    req2 = ChatRequest(
        message="Hello\x00 \x0bworld!",
        event_id="kerala_2018",
        disaster_type="flood"
    )
    assert req2.message == "Hello world!"

    # Test empty message after sanitization raises ValidationError
    with pytest.raises(ValidationError):
        ChatRequest(
            message="   <script></script>  \x00 ",
            event_id="kerala_2018",
            disaster_type="flood"
        )


def test_global_exception_handler_production():
    """Verify that unhandled exceptions do not leak details in production (DEMO_MODE=False)."""
    # Create a dummy FastAPI app to test global exception handling in isolation
    app = FastAPI()
    
    # Temporarily force demo mode to False to simulate production
    original_demo_mode = settings.DEMO_MODE
    settings.DEMO_MODE = False
    
    try:
        from backend.main import global_exception_handler
        app.add_exception_handler(Exception, global_exception_handler)

        @app.get("/error-route")
        def error_route():
            raise RuntimeError("Database connection password=supersecret failed")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/error-route")
        
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "Internal server error"
        assert data["detail"] == "An unexpected error occurred."
        assert "supersecret" not in data["detail"]
        assert "RuntimeError" not in data["detail"]
    finally:
        settings.DEMO_MODE = original_demo_mode


def test_rate_limiting_middleware():
    """Verify that RateLimitMiddleware enforces limits for heavy and global requests."""
    app = FastAPI()
    # Configure tight rate limits for quick testing: global=5, heavy=2
    app.add_middleware(
        RateLimitMiddleware,
        global_limit=5,
        global_window=10,
        heavy_limit=2,
        heavy_window=10
    )

    @app.get("/api/analyze")
    def dummy_analyze():
        return {"status": "ok"}

    @app.get("/light-route")
    def dummy_light():
        return {"status": "ok"}

    client = TestClient(app)
    headers = {"x-enforce-rate-limit": "true"}

    # 1. Test heavy endpoint rate limiting (limit = 2)
    response = client.get("/api/analyze", headers=headers)
    assert response.status_code == 200
    response = client.get("/api/analyze", headers=headers)
    assert response.status_code == 200
    
    # Third request should be blocked by heavy rate limit
    response = client.get("/api/analyze", headers=headers)
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]

    # 2. Test global rate limiting (limit = 5) on a non-heavy route
    # Resetting client session or using different paths
    for _ in range(3):
        # We already sent 2 successful global requests from client (for dummy_analyze)
        # So we can send 3 more to dummy_light before reaching global limit of 5.
        response = client.get("/light-route", headers=headers)
        assert response.status_code == 200

    # 6th request globally should be blocked
    response = client.get("/light-route", headers=headers)
    assert response.status_code == 429
    assert "Too many requests" in response.json()["detail"]
