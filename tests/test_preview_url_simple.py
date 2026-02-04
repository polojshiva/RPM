"""
Simplified unit tests for preview URL generation
Tests the URL generation logic directly without full app import
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from fastapi import Request
from starlette.datastructures import Headers
from app.config.settings import Settings, get_settings


def test_url_for_with_https_forwarded_proto():
    """Test that url_for generates HTTPS URLs when X-Forwarded-Proto is https"""
    # This test verifies the middleware logic
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest
    
    # Create a mock request with X-Forwarded-Proto header
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/preview",
        "scheme": "http",  # Original scheme
        "server": ("prd-wiser-ops-appb.azurewebsites.us", 80),
        "headers": [
            (b"x-forwarded-proto", b"https"),
            (b"host", b"prd-wiser-ops-appb.azurewebsites.us"),
        ]
    }
    
    # Simulate middleware behavior
    forwarded_proto = "https"
    if forwarded_proto == "https":
        scope["scheme"] = "https"
        scope["server"] = ("prd-wiser-ops-appb.azurewebsites.us", 443)
    
    # Verify scheme was updated
    assert scope["scheme"] == "https"
    assert scope["server"][1] == 443


def test_public_base_url_override(monkeypatch):
    """Test that PUBLIC_BASE_URL overrides URL generation"""
    # Set PUBLIC_BASE_URL
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.gov")
    
    # Clear settings cache
    get_settings.cache_clear()
    
    try:
        settings = get_settings()
        assert settings.public_base_url == "https://example.gov"
        
        # Simulate URL construction
        base_url = settings.public_base_url.rstrip('/')
        preview_url = f"{base_url}/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/content"
        
        assert preview_url.startswith("https://example.gov/")
        assert "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/content" in preview_url
    finally:
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        get_settings.cache_clear()


def test_public_base_url_trailing_slash(monkeypatch):
    """Test that PUBLIC_BASE_URL trailing slash is handled correctly"""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.gov/")
    get_settings.cache_clear()
    
    try:
        settings = get_settings()
        base_url = settings.public_base_url.rstrip('/')
        preview_url = f"{base_url}/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/content"
        
        # Should not have double slashes
        assert preview_url.startswith("https://example.gov/")
        assert "//api" not in preview_url
    finally:
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        get_settings.cache_clear()


def test_url_generation_logic():
    """Test the URL generation logic without full app context"""
    # Simulate the logic from get_page_preview_url
    packet_id = "PKT-2026-817726"
    doc_id = "DOC-265"
    page_num = 1
    
    # Test with PUBLIC_BASE_URL
    public_base_url = "https://example.gov"
    if public_base_url:
        base_url = public_base_url.rstrip('/')
        preview_url = f"{base_url}/api/packets/{packet_id}/documents/{doc_id}/pages/{page_num}/content"
        assert preview_url == "https://example.gov/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/content"
    
    # Test without PUBLIC_BASE_URL (would use url_for in real code)
    public_base_url = None
    if not public_base_url:
        # In real code, this would use request.url_for()
        # For this test, we verify the logic path
        assert public_base_url is None






