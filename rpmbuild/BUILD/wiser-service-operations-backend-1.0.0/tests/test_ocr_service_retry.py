"""
Unit tests for OCR service retry logic:
- Retry on 502/503 errors with longer backoff
- Retry on timeouts
- Max retries enforcement
"""
import pytest
import sys
import time
from unittest.mock import Mock, patch, MagicMock

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.services.ocr_service import OCRService, OCRServiceError
import httpx


class TestOCRServiceRetry:
    """Test OCR service retry logic"""
    
    @pytest.fixture
    def ocr_service(self):
        """Create OCR service with test config"""
        with patch('app.services.ocr_service.settings') as mock_settings:
            mock_settings.ocr_base_url = "http://test-ocr-service"
            mock_settings.ocr_timeout_seconds = 120
            mock_settings.ocr_max_retries = 5
            service = OCRService()
            return service
    
    def test_retry_on_502_error_with_longer_backoff(self, ocr_service):
        """Test that 502 errors use longer backoff"""
        # Create a temporary PDF file for testing
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(b"%PDF-1.4\nfake pdf content")
            tmp_path = tmp_file.name
        
        try:
            # Mock httpx client to return 502 errors
            mock_response = Mock()
            mock_response.status_code = 502
            mock_response.text = "<html>502 Bad Gateway</html>"
            
            mock_client = Mock()
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            
            with patch('httpx.Client', return_value=mock_client):
                with patch('time.sleep') as mock_sleep:
                    # Should raise after max retries
                    with pytest.raises(OCRServiceError):
                        ocr_service.run_ocr_on_pdf(tmp_path)
                    
                    # Verify retries were attempted
                    assert mock_client.post.call_count == 5
                    
                    # Verify longer backoff for 502 (2^attempt: 2s, 4s, 8s, 16s, 32s)
                    sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
                    # First retry: 2^1 = 2s
                    # Second retry: 2^2 = 4s
                    # Third retry: 2^3 = 8s
                    # Fourth retry: 2^4 = 16s
                    assert len(sleep_calls) == 4  # 4 retries (5 total attempts)
                    assert sleep_calls[0] == 2  # First backoff: 2s
                    assert sleep_calls[1] == 4  # Second backoff: 4s
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    def test_success_after_retry(self, ocr_service):
        """Test that retry eventually succeeds"""
        import tempfile
        import os
        
        # Create a temporary PDF file for testing
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(b"%PDF-1.4\nfake pdf content")
            tmp_path = tmp_file.name
        
        try:
            call_count = {'count': 0}
            
            def mock_post_side_effect(*args, **kwargs):
                call_count['count'] += 1
                mock_response = Mock()
                if call_count['count'] < 3:
                    # First 2 attempts fail
                    mock_response.status_code = 502
                    mock_response.text = "502 Bad Gateway"
                else:
                    # 3rd attempt succeeds
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        'fields': {'test': {'value': 'data', 'confidence': 0.9}},
                        'overall_document_confidence': 0.9,
                        'model_id': 'test',
                        'coversheet_type': '',
                        'doc_type': 'coversheet-extraction'
                    }
                return mock_response
            
            mock_client = Mock()
            mock_client.post.side_effect = mock_post_side_effect
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            
            with patch('httpx.Client', return_value=mock_client):
                with patch('time.sleep'):
                    result = ocr_service.run_ocr_on_pdf(tmp_path)
                    
                    # Should succeed on 3rd attempt
                    assert call_count['count'] == 3
                    assert result is not None
                    assert 'fields' in result
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    def test_max_retries_enforced(self, ocr_service):
        """Test that max retries is enforced"""
        import tempfile
        import os
        
        # Create a temporary PDF file for testing
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            tmp_file.write(b"%PDF-1.4\nfake pdf content")
            tmp_path = tmp_file.name
        
        try:
            mock_response = Mock()
            mock_response.status_code = 502
            mock_response.text = "502 Bad Gateway"
            
            mock_client = Mock()
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            
            with patch('httpx.Client', return_value=mock_client):
                with patch('time.sleep'):
                    # Should raise after max retries (5)
                    with pytest.raises(OCRServiceError):
                        ocr_service.run_ocr_on_pdf(tmp_path)
                    
                    # Verify exactly max_retries attempts
                    assert mock_client.post.call_count == 5
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

