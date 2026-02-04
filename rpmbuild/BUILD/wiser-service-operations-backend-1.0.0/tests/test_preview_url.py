"""
Unit tests for preview URL generation
Tests that preview URLs use correct HTTPS scheme when behind proxy
"""
import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import Request
from app.models.user import User, UserRole
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.config.settings import Settings, get_settings

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.main import app


# Mock user for testing
MOCK_USER = User(
    id="test-user-id",
    username="testuser",
    email="test@example.com",
    name="Test User",
    roles=[UserRole.USER]
)


def mock_get_current_user():
    """Mock dependency to bypass authentication"""
    return MOCK_USER


def mock_get_db():
    """Mock database dependency"""
    db = MagicMock()
    # Mock packet
    mock_packet = Mock(spec=PacketDB)
    mock_packet.packet_id = 1
    mock_packet.external_id = "PKT-2026-817726"
    db.query.return_value.filter.return_value.first.return_value = mock_packet
    
    # Mock document
    mock_document = Mock(spec=PacketDocumentDB)
    mock_document.packet_id = 1
    mock_document.external_id = "DOC-265"
    mock_document.pages_metadata = {
        "pages": [
            {
                "page_number": 1,
                "blob_path": "service_ops_processing/2026/01-06/test-uuid/packet_265_page_0001.pdf",
                "relative_path": "service_ops_processing/2026/01-06/test-uuid/packet_265_page_0001.pdf"
            }
        ]
    }
    
    # Configure query chain for document
    def query_side_effect(model):
        query_mock = MagicMock()
        if model == PacketDB:
            query_mock.filter.return_value.first.return_value = mock_packet
        elif model == PacketDocumentDB:
            query_mock.filter.return_value.first.return_value = mock_document
        return query_mock
    
    db.query.side_effect = query_side_effect
    yield db


@pytest.fixture
def client():
    """Create test client with mocked dependencies"""
    from app.auth.dependencies import get_current_user
    from app.services.db import get_db
    
    # Override FastAPI dependencies
    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_db] = mock_get_db
    
    try:
        yield TestClient(app)
    finally:
        # Clear overrides
        app.dependency_overrides.clear()


def test_preview_url_http_request(client):
    """Test preview URL generation with plain HTTP request"""
    response = client.get(
        "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/preview",
        headers={"Authorization": "Bearer fake-token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "previewUrl" in data["data"]
    
    # Should use http://testserver/... for plain HTTP request
    preview_url = data["data"]["previewUrl"]
    assert preview_url.startswith("http://testserver/")
    assert "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/content" in preview_url


def test_preview_url_https_with_forwarded_proto(client):
    """Test preview URL generation with X-Forwarded-Proto: https header"""
    response = client.get(
        "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/preview",
        headers={
            "Authorization": "Bearer fake-token",
            "X-Forwarded-Proto": "https",
            "Host": "prd-wiser-ops-appb.azurewebsites.us"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "previewUrl" in data["data"]
    
    # Should use https:// with forwarded host
    preview_url = data["data"]["previewUrl"]
    assert preview_url.startswith("https://")
    assert "prd-wiser-ops-appb.azurewebsites.us" in preview_url
    assert "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/content" in preview_url


def test_preview_url_with_public_base_url(client, monkeypatch):
    """Test preview URL generation with PUBLIC_BASE_URL environment variable"""
    # Set PUBLIC_BASE_URL
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.gov")
    
    # Clear settings cache to reload with new env var
    get_settings.cache_clear()
    
    try:
        response = client.get(
            "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/preview",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "previewUrl" in data["data"]
        
        # Should use PUBLIC_BASE_URL
        preview_url = data["data"]["previewUrl"]
        assert preview_url.startswith("https://example.gov/")
        assert "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/content" in preview_url
    finally:
        # Clean up: remove env var and clear cache
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        get_settings.cache_clear()


def test_preview_url_with_public_base_url_trailing_slash(client, monkeypatch):
    """Test that PUBLIC_BASE_URL trailing slash is handled correctly"""
    # Set PUBLIC_BASE_URL with trailing slash
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.gov/")
    
    # Clear settings cache
    get_settings.cache_clear()
    
    try:
        response = client.get(
            "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/preview",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Should not have double slashes
        preview_url = data["data"]["previewUrl"]
        assert preview_url.startswith("https://example.gov/")
        assert "//api" not in preview_url  # No double slash
        assert "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/content" in preview_url
    finally:
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        get_settings.cache_clear()


def test_preview_url_missing_page(client):
    """Test preview URL generation when page is not found"""
    from app.services.db import get_db
    
    def mock_get_db_no_pages():
        db_mock = MagicMock()
        mock_packet = Mock(spec=PacketDB)
        mock_packet.packet_id = 1
        mock_packet.external_id = "PKT-2026-817726"
        
        mock_document = Mock(spec=PacketDocumentDB)
        mock_document.packet_id = 1
        mock_document.external_id = "DOC-265"
        mock_document.pages_metadata = {"pages": []}  # No pages
        
        def query_side_effect(model):
            query_mock = MagicMock()
            if model == PacketDB:
                query_mock.filter.return_value.first.return_value = mock_packet
            elif model == PacketDocumentDB:
                query_mock.filter.return_value.first.return_value = mock_document
            return query_mock
        
        db_mock.query.side_effect = query_side_effect
        yield db_mock
    
    # Override get_db for this test
    app.dependency_overrides[get_db] = mock_get_db_no_pages
    
    try:
        response = client.get(
            "/api/packets/PKT-2026-817726/documents/DOC-265/pages/1/preview",
            headers={"Authorization": "Bearer fake-token"}
        )
        
        assert response.status_code == 404
    finally:
        # Restore original mock
        app.dependency_overrides[get_db] = mock_get_db

