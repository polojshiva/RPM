"""
Unit tests for blob path helper utility
Tests the resolve_blob_path function with various prefix configurations
"""
import pytest
from unittest.mock import patch, MagicMock
from app.utils.blob_path_helper import resolve_blob_path, get_blob_prefix, log_blob_access


class TestResolveBlobPath:
    """Tests for resolve_blob_path function"""
    
    def test_no_prefix_returns_path_unchanged(self):
        """Test that when prefix is not set, path is returned unchanged"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value=None):
            result = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert result == "2026/01-06/uuid/page.pdf"
    
    def test_prefix_added_when_set(self):
        """Test that prefix is prepended when configured"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            result = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert result == "service_ops_processing/2026/01-06/uuid/page.pdf"
    
    def test_prefix_with_leading_slash_normalized(self):
        """Test that prefix with leading slash is normalized"""
        # Mock settings to return unsanitized value, get_blob_prefix will sanitize it
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "/service_ops_processing"
            result = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert result == "service_ops_processing/2026/01-06/uuid/page.pdf"
    
    def test_prefix_with_trailing_slash_normalized(self):
        """Test that prefix with trailing slash is normalized"""
        # Mock settings to return unsanitized value, get_blob_prefix will sanitize it
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "service_ops_processing/"
            result = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert result == "service_ops_processing/2026/01-06/uuid/page.pdf"
    
    def test_prefix_with_both_slashes_normalized(self):
        """Test that prefix with both leading and trailing slashes is normalized"""
        # Mock settings to return unsanitized value, get_blob_prefix will sanitize it
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "/service_ops_processing/"
            result = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert result == "service_ops_processing/2026/01-06/uuid/page.pdf"
    
    def test_relative_path_with_leading_slash_normalized(self):
        """Test that relative path with leading slash is normalized"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            result = resolve_blob_path("/2026/01-06/uuid/page.pdf")
            assert result == "service_ops_processing/2026/01-06/uuid/page.pdf"
    
    def test_no_double_slashes(self):
        """Test that no double slashes are produced"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            result = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert "//" not in result
            assert result == "service_ops_processing/2026/01-06/uuid/page.pdf"
    
    def test_empty_path_returns_empty(self):
        """Test that empty path returns empty string"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            result = resolve_blob_path("")
            assert result == ""
    
    def test_whitespace_prefix_stripped(self):
        """Test that whitespace in prefix is stripped"""
        # Mock settings to return unsanitized value, get_blob_prefix will sanitize it
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "  service_ops_processing  "
            result = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert result == "service_ops_processing/2026/01-06/uuid/page.pdf"
    
    def test_complex_path_with_prefix(self):
        """Test complex path with multiple levels"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            result = resolve_blob_path("2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf")
            assert result == "service_ops_processing/2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf"
    
    def test_idempotent_already_has_prefix(self):
        """Test that calling resolve_blob_path on an already-resolved path returns it unchanged (idempotent)"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            # First call adds prefix
            result1 = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert result1 == "service_ops_processing/2026/01-06/uuid/page.pdf"
            
            # Second call with already-resolved path returns unchanged (idempotent)
            result2 = resolve_blob_path(result1)
            assert result2 == "service_ops_processing/2026/01-06/uuid/page.pdf"
            assert result2 == result1  # Same result
    
    def test_idempotent_multiple_calls(self):
        """Test that multiple calls with same input return same result"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            path = "2026/01-06/uuid/page.pdf"
            result1 = resolve_blob_path(path)
            result2 = resolve_blob_path(path)
            result3 = resolve_blob_path(result1)  # Call with already-resolved path
            
            assert result1 == result2 == result3 == "service_ops_processing/2026/01-06/uuid/page.pdf"


class TestGetBlobPrefix:
    """Tests for get_blob_prefix function"""
    
    def test_prefix_not_set_returns_none(self):
        """Test that None is returned when prefix is not set"""
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = None
            result = get_blob_prefix()
            assert result is None
    
    def test_prefix_empty_string_returns_none(self):
        """Test that empty string returns None"""
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = ""
            result = get_blob_prefix()
            assert result is None
    
    def test_prefix_whitespace_only_returns_none(self):
        """Test that whitespace-only prefix returns None"""
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "   "
            result = get_blob_prefix()
            assert result is None
    
    def test_prefix_with_slashes_stripped(self):
        """Test that slashes are stripped from prefix"""
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "/service_ops_processing/"
            result = get_blob_prefix()
            assert result == "service_ops_processing"
    
    def test_prefix_with_whitespace_stripped(self):
        """Test that whitespace is stripped from prefix"""
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "  service_ops_processing  "
            result = get_blob_prefix()
            assert result == "service_ops_processing"
    
    def test_prefix_normal_value_returned(self):
        """Test that normal prefix value is returned"""
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "service_ops_processing"
            result = get_blob_prefix()
            assert result == "service_ops_processing"


class TestLogBlobAccess:
    """Tests for log_blob_access function"""
    
    def test_log_blob_access_with_all_context(self, caplog):
        """Test that log_blob_access logs all provided context"""
        with caplog.at_level("INFO"):
            log_blob_access(
                container_name="service-ops-processing",
                resolved_blob_path="service_ops_processing/2026/01-06/uuid/page.pdf",
                packet_id="PKT-2026-123",
                doc_id="DOC-456",
                page_num=4
            )
        
        assert "container='service-ops-processing'" in caplog.text
        assert "resolved_blob_path='service_ops_processing/2026/01-06/uuid/page.pdf'" in caplog.text
        assert "packet_id=PKT-2026-123" in caplog.text
        assert "doc_id=DOC-456" in caplog.text
        assert "page_num=4" in caplog.text
    
    def test_log_blob_access_without_context(self, caplog):
        """Test that log_blob_access works without optional context"""
        with caplog.at_level("INFO"):
            log_blob_access(
                container_name="service-ops-processing",
                resolved_blob_path="2026/01-06/uuid/page.pdf"
            )
        
        assert "container='service-ops-processing'" in caplog.text
        assert "resolved_blob_path='2026/01-06/uuid/page.pdf'" in caplog.text
        assert "context=[N/A]" in caplog.text
    
    def test_log_blob_access_shows_prefix_info(self, caplog):
        """Test that log_blob_access shows prefix information"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            with caplog.at_level("INFO"):
                log_blob_access(
                    container_name="service-ops-processing",
                    resolved_blob_path="service_ops_processing/2026/01-06/uuid/page.pdf"
                )
            
            assert "prefix=service_ops_processing" in caplog.text
    
    def test_log_blob_access_shows_no_prefix_info(self, caplog):
        """Test that log_blob_access shows 'no prefix' when prefix is not set"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value=None):
            with caplog.at_level("INFO"):
                log_blob_access(
                    container_name="service-ops-processing",
                    resolved_blob_path="2026/01-06/uuid/page.pdf"
                )
            
            assert "no prefix" in caplog.text


class TestIntegrationScenarios:
    """Integration tests for real-world scenarios"""
    
    def test_scenario_1_prefix_unset(self):
        """Scenario: Prefix not set, path should be unchanged"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value=None):
            result = resolve_blob_path("2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf")
            assert result == "2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf"
    
    def test_scenario_2_prefix_set(self):
        """Scenario: Prefix set to service_ops_processing"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            result = resolve_blob_path("2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf")
            assert result == "service_ops_processing/2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf"
    
    def test_scenario_3_prefix_with_slashes(self):
        """Scenario: Prefix has slashes, should be normalized"""
        # Mock settings to return unsanitized value, get_blob_prefix will sanitize it
        with patch('app.utils.blob_path_helper.settings') as mock_settings:
            mock_settings.azure_storage_blob_prefix = "/service_ops_processing/"
            result = resolve_blob_path("2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf")
            assert result == "service_ops_processing/2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf"
    
    def test_scenario_4_path_with_leading_slash(self):
        """Scenario: Path has leading slash, should be normalized"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value="service_ops_processing"):
            result = resolve_blob_path("/2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf")
            assert result == "service_ops_processing/2026/01-06/8f6493e9-39a5-4371-9804-c6d6f522a459/packet_331_pages/packet_331_page_0004.pdf"
    
    def test_scenario_5_empty_prefix_after_sanitization(self):
        """Scenario: Prefix is only slashes/whitespace, should return None"""
        with patch('app.utils.blob_path_helper.get_blob_prefix', return_value=None):
            result = resolve_blob_path("2026/01-06/uuid/page.pdf")
            assert result == "2026/01-06/uuid/page.pdf"

