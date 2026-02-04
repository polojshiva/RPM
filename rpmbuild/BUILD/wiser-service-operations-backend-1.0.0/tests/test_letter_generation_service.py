"""
Unit tests for LetterGenerationService
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import httpx

from app.services.letter_generation_service import LetterGenerationService, LetterGenerationError
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB


@pytest.fixture
def mock_db():
    """Mock database session"""
    return Mock()


@pytest.fixture
def mock_packet():
    """Mock PacketDB"""
    packet = Mock(spec=PacketDB)
    packet.packet_id = 1
    packet.external_id = "SVC-2026-000001"
    packet.decision_tracking_id = "123e4567-e89b-12d3-a456-426614174000"
    packet.channel_type_id = 3  # ESMD
    packet.provider_name = "Test Provider"
    packet.provider_npi = "1234567890"
    packet.provider_fax = "555-123-4567"
    packet.beneficiary_name = "Doe, John"
    packet.beneficiary_mbi = "1WX2YZ3AB45"
    packet.received_date = datetime(2026, 1, 11)  # Match expected date format
    return packet


@pytest.fixture
def mock_packet_decision():
    """Mock PacketDecisionDB"""
    decision = Mock(spec=PacketDecisionDB)
    decision.packet_decision_id = 1
    decision.decision_outcome = "AFFIRM"
    decision.decision_subtype = "STANDARD_PA"
    decision.part_type = "B"
    decision.utn = "JLB86260080030"
    decision.letter_medical_docs = []
    decision.esmd_request_payload = {
        "procedures": [
            {
                "procedure_code": "K0856",
                "review_codes": "A1",
                "program_codes": "B1"
            }
        ]
    }
    return decision


@pytest.fixture
def mock_packet_document():
    """Mock PacketDocumentDB"""
    doc = Mock(spec=PacketDocumentDB)
    doc.packet_document_id = 1
    doc.extracted_fields = {
        "fields": {
            "provider_address": {"value": "123 Main St"},
            "provider_city": {"value": "Houston"},
            "provider_state": {"value": "TX"},
            "provider_zip": {"value": "77001"},
            "provider_phone": {"value": "555-111-2222"},
            "patient_date_of_birth": {"value": "1947-09-21"}
        }
    }
    doc.updated_extracted_fields = None
    return doc


@pytest.fixture
def letter_service(mock_db):
    """LetterGenerationService instance"""
    with patch('app.services.letter_generation_service.settings') as mock_settings:
        mock_settings.lettergen_base_url = "https://lettergen-api.example.com"
        mock_settings.lettergen_timeout_seconds = 60
        mock_settings.lettergen_max_retries = 3
        mock_settings.lettergen_retry_base_seconds = 1.0
        service = LetterGenerationService(mock_db)
        return service


class TestBuildAffirmationRequest:
    """Test building affirmation request payload"""
    
    def test_build_affirmation_request_success(
        self, letter_service, mock_packet, mock_packet_decision, mock_packet_document
    ):
        """Test building affirmation request with all fields - flat structure matching API contract"""
        payload = letter_service._build_affirmation_request(
            mock_packet, mock_packet_decision, mock_packet_document
        )
        
        # Core API contract fields (flat structure)
        assert payload["patient_name"] == "Doe, John"
        assert payload["patient_id"] == "1WX2YZ3AB45"
        assert payload["date"] == "2026-01-11"
        assert payload["provider_name"] == "Test Provider"
        assert payload["channel"] == "ESMD"  # channel_type_id = 3
        assert payload["fax_number"] is None  # Not Fax channel
        
        # Additional fields (API allows additionalProperties: true)
        assert payload["case_id"] == "SVC-2026-000001"
        assert payload["decision_outcome"] == "AFFIRM"
        assert payload["decision_subtype"] == "STANDARD_PA"
        assert payload["part_type"] == "B"
        assert payload["provider_npi"] == "1234567890"
        assert payload["utn"] == "JLB86260080030"
        assert "procedures" in payload
    
    def test_build_affirmation_request_missing_fields(
        self, letter_service, mock_packet, mock_packet_decision, mock_packet_document
    ):
        """Test building affirmation request with missing optional fields"""
        mock_packet.provider_fax = None
        mock_packet_decision.utn = None
        
        payload = letter_service._build_affirmation_request(
            mock_packet, mock_packet_decision, mock_packet_document
        )
        
        # Core fields should still be present (can be empty strings)
        assert payload["patient_name"] == "Doe, John"
        assert payload["patient_id"] == "1WX2YZ3AB45"
        assert payload["provider_name"] == "Test Provider"
        # fax_number should be None for non-Fax channels
        assert payload["fax_number"] is None
        # utn should be None
        assert payload["utn"] is None


class TestBuildNonAffirmationRequest:
    """Test building non-affirmation request payload"""
    
    def test_build_non_affirmation_request_success(
        self, letter_service, mock_packet, mock_packet_decision, mock_packet_document
    ):
        """Test building non-affirmation request - flat structure matching API contract"""
        mock_packet_decision.decision_outcome = "NON_AFFIRM"
        
        payload = letter_service._build_non_affirmation_request(
            mock_packet, mock_packet_decision, mock_packet_document
        )
        
        # Core API contract fields
        assert payload["patient_name"] == "Doe, John"
        assert payload["patient_id"] == "1WX2YZ3AB45"
        assert payload["provider_name"] == "Test Provider"
        
        # Decision outcome in additional fields
        assert payload["decision_outcome"] == "NON_AFFIRM"
        assert "review_codes" in payload
        assert "program_codes" in payload


class TestBuildDismissalRequest:
    """Test building dismissal request payload"""
    
    def test_build_dismissal_request_success(
        self, letter_service, mock_packet, mock_packet_decision, mock_packet_document
    ):
        """Test building dismissal request - flat structure matching API contract"""
        mock_packet_decision.decision_outcome = "DISMISSAL"
        mock_packet_decision.denial_reason = "MISSING_FIELDS"
        mock_packet_decision.denial_details = {"missingFields": ["provider_fax"]}
        
        payload = letter_service._build_dismissal_request(
            mock_packet, mock_packet_decision, mock_packet_document
        )
        
        # Core API contract fields
        assert payload["patient_name"] == "Doe, John"
        assert payload["patient_id"] == "1WX2YZ3AB45"
        assert payload["provider_name"] == "Test Provider"
        
        # Decision fields in additional fields
        assert payload["decision_outcome"] == "DISMISSAL"
        assert payload["denial_reason"] == "MISSING_FIELDS"
        assert payload["denial_details"] == {"missingFields": ["provider_fax"]}


class TestCallLetterGenAPI:
    """Test calling LetterGen API"""
    
    @patch('httpx.Client')
    def test_call_lettergen_api_success(self, mock_client_class, letter_service):
        """Test successful API call"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "blob_url": "https://storage.example.com/letter.pdf",
            "filename": "letter.pdf",
            "file_size_bytes": 12345,
            "template_used": "affirmation_v1",
            "generated_at": "2026-01-15T10:00:00Z",
            "inbound_json_blob_url": "https://storage.example.com/inbound.json",
            "inbound_metadata_blob_url": "https://storage.example.com/metadata.json"
        }
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        response = letter_service._call_lettergen_api_with_retry(
            "/api/v2/affirmation",
            {"case_id": "SVC-2026-000001"}
        )
        
        assert response["blob_url"] == "https://storage.example.com/letter.pdf"
        assert response["filename"] == "letter.pdf"
    
    @patch('httpx.Client')
    def test_call_lettergen_api_422_validation_error(self, mock_client_class, letter_service):
        """Test API returns 422 validation error (no retry)"""
        mock_response = Mock()
        mock_response.status_code = 422
        mock_response.json.return_value = {
            "message": "Validation error",
            "errors": {"provider_fax": "Required field missing"}
        }
        mock_response.content = b'{"message": "Validation error"}'
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        with pytest.raises(LetterGenerationError) as exc_info:
            letter_service._call_lettergen_api_with_retry(
                "/api/v2/affirmation",
                {"case_id": "SVC-2026-000001"}
            )
        
        assert "422" in str(exc_info.value)
        assert "Validation error" in str(exc_info.value)
    
    @patch('httpx.Client')
    @patch('time.sleep')
    def test_call_lettergen_api_500_retry(self, mock_sleep, mock_client_class, letter_service):
        """Test API returns 500, then succeeds on retry"""
        # First call: 500
        # Second call: 200
        mock_response_500 = Mock()
        mock_response_500.status_code = 500
        
        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            "blob_url": "https://storage.example.com/letter.pdf",
            "filename": "letter.pdf"
        }
        
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client.post.side_effect = [mock_response_500, mock_response_200]
        mock_client_class.return_value = mock_client
        
        response = letter_service._call_lettergen_api_with_retry(
            "/api/v2/affirmation",
            {"case_id": "SVC-2026-000001"}
        )
        
        assert response["blob_url"] == "https://storage.example.com/letter.pdf"
        assert mock_client.post.call_count == 2
        mock_sleep.assert_called_once()  # Should sleep before retry
    
    @patch('httpx.Client')
    @patch('time.sleep')
    def test_call_lettergen_api_timeout_retry(self, mock_sleep, mock_client_class, letter_service):
        """Test API timeout, then succeeds on retry"""
        mock_client = Mock()
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client.post.side_effect = [
            httpx.TimeoutException("Request timed out"),
            Mock(status_code=200, json=lambda: {"blob_url": "https://storage.example.com/letter.pdf"})
        ]
        mock_client_class.return_value = mock_client
        
        response = letter_service._call_lettergen_api_with_retry(
            "/api/v2/affirmation",
            {"case_id": "SVC-2026-000001"}
        )
        
        assert response["blob_url"] == "https://storage.example.com/letter.pdf"
        assert mock_client.post.call_count == 2


class TestGenerateLetter:
    """Test generate_letter method"""
    
    @patch.object(LetterGenerationService, '_call_lettergen_api_with_retry')
    def test_generate_letter_affirmation_success(
        self, mock_api_call, letter_service, mock_packet, mock_packet_decision, mock_packet_document
    ):
        """Test successful affirmation letter generation"""
        mock_api_call.return_value = {
            "blob_url": "https://storage.example.com/letter.pdf",
            "filename": "letter.pdf",
            "file_size_bytes": 12345,
            "template_used": "affirmation_v1",
            "generated_at": "2026-01-15T10:00:00Z"
        }
        
        result = letter_service.generate_letter(
            mock_packet, mock_packet_decision, mock_packet_document, "affirmation"
        )
        
        assert result["blob_url"] == "https://storage.example.com/letter.pdf"
        assert result["letter_type"] == "affirmation"
        assert result["generated_by"] == "ServiceOps"
        mock_api_call.assert_called_once()
    
    def test_generate_letter_missing_base_url(
        self, mock_db, mock_packet, mock_packet_decision, mock_packet_document
    ):
        """Test letter generation fails when base URL not configured"""
        with patch('app.services.letter_generation_service.settings') as mock_settings:
            mock_settings.lettergen_base_url = ""
            mock_settings.lettergen_timeout_seconds = 60
            mock_settings.lettergen_max_retries = 3
            mock_settings.lettergen_retry_base_seconds = 1.0
            service = LetterGenerationService(mock_db)
            
            with pytest.raises(LetterGenerationError) as exc_info:
                service.generate_letter(
                    mock_packet, mock_packet_decision, mock_packet_document, "affirmation"
                )
            
            assert "LETTERGEN_BASE_URL not configured" in str(exc_info.value)


class TestReprocessByUrls:
    """Test reprocess_by_urls method"""
    
    @patch.object(LetterGenerationService, '_call_lettergen_api_with_retry')
    def test_reprocess_by_urls_success(self, mock_api_call, letter_service):
        """Test successful reprocessing"""
        mock_api_call.return_value = {
            "blob_url": "https://storage.example.com/letter.pdf",
            "filename": "letter.pdf"
        }
        
        result = letter_service.reprocess_by_urls(
            "https://storage.example.com/inbound.json",
            "https://storage.example.com/metadata.json"
        )
        
        assert result["blob_url"] == "https://storage.example.com/letter.pdf"
        mock_api_call.assert_called_once()
        call_args = mock_api_call.call_args
        # The endpoint parameter is just the path, not the full URL
        assert call_args[0][0] == "/api/v2/recovery"
        assert "inbound_json_blob_url" in call_args[0][1]
        assert "inbound_metadata_blob_url" in call_args[0][1]

