"""
Unit tests for submission date extraction functionality.

Tests the extraction of submission dates from payloads based on channel type,
with date-only normalization to midnight UTC.
"""
import pytest
import sys
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.services.document_processor import DocumentProcessor
from app.services.payload_parser import ParsedPayloadModel, DocumentModel


class TestSubmissionDateExtraction:
    """Test suite for submission date extraction"""
    
    @pytest.fixture
    def processor(self):
        """Create a DocumentProcessor instance for testing"""
        # Mock DocumentProcessor initialization to avoid PDF library dependency
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    return DocumentProcessor()
    
    @pytest.fixture
    def esmd_payload(self) -> Dict[str, Any]:
        """ESMD payload with submission_metadata.creationTime"""
        return {
            "decision_tracking_id": "test-esmd-123",
            "submission_metadata": {
                "creationTime": "2026-01-06T14:25:33.4392211-05:00"
            },
            "documents": []
        }
    
    @pytest.fixture
    def portal_payload(self) -> Dict[str, Any]:
        """Portal payload with ocr.fields['Submitted Date'].value"""
        return {
            "decision_tracking_id": "test-portal-123",
            "ocr": {
                "fields": {
                    "Submitted Date": {
                        "value": "2026-01-07T00:00:00+00:00",
                        "confidence": 1.0
                    }
                }
            },
            "documents": []
        }
    
    @pytest.fixture
    def fax_payload(self) -> Dict[str, Any]:
        """Fax payload with submission_metadata.creationTime (extracted_fields populated after OCR)"""
        return {
            "decision_tracking_id": "test-fax-123",
            "submission_metadata": {
                "creationTime": "2026-01-08T14:30:00-05:00"
            },
            "documents": []
        }
    
    @pytest.fixture
    def fax_extracted_fields(self) -> Dict[str, Any]:
        """Fax extracted_fields after OCR (used for post-OCR update)"""
        return {
            "fields": {
                "Submitted Date": {
                    "value": "2026-01-08T00:00:00+00:00",
                    "confidence": 0.95
                }
            }
        }
    
    @pytest.fixture
    def parsed_esmd(self, esmd_payload):
        """Parsed ESMD payload"""
        return ParsedPayloadModel(
            decision_tracking_id="test-esmd-123",
            unique_id="test-esmd-123",
            message_type="ingest_file_package",
            esmd_transaction_id=None,
            submission_metadata=esmd_payload.get("submission_metadata", {}),
            documents=[DocumentModel(
                document_unique_identifier="doc1",
                file_name="test.pdf",
                mime_type="application/pdf",
                file_size=1000,
                source_absolute_url="https://example.com/test.pdf"
            )]
        )
    
    @pytest.fixture
    def parsed_portal(self, portal_payload):
        """Parsed Portal payload"""
        return ParsedPayloadModel(
            decision_tracking_id="test-portal-123",
            unique_id="test-portal-123",
            message_type="ingest_file_package",
            esmd_transaction_id=None,
            submission_metadata={},
            documents=[DocumentModel(
                document_unique_identifier="doc1",
                file_name="test.pdf",
                mime_type="application/pdf",
                file_size=1000,
                source_absolute_url="https://example.com/test.pdf"
            )]
        )
    
    @pytest.fixture
    def parsed_fax(self, fax_payload):
        """Parsed Fax payload"""
        return ParsedPayloadModel(
            decision_tracking_id="test-fax-123",
            unique_id="test-fax-123",
            message_type="ingest_file_package",
            esmd_transaction_id=None,
            submission_metadata=fax_payload.get("submission_metadata", {}),
            documents=[DocumentModel(
                document_unique_identifier="doc1",
                file_name="test.pdf",
                mime_type="application/pdf",
                file_size=1000,
                source_absolute_url="https://example.com/test.pdf"
            )]
        )
    
    def test_parse_date_esmd_format(self, processor):
        """Test parsing ESMD date format - returns raw timestamp (not normalized)"""
        date_str = "2026-01-06T14:25:33.4392211-05:00"
        result = processor._parse_date(date_str)
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 6
        # Should preserve original time (converted to UTC)
        # 14:25:33 EST (-05:00) = 19:25:33 UTC
        assert result.hour == 19
        assert result.minute == 25
        assert result.second == 33
        assert result.tzinfo == timezone.utc
    
    def test_parse_date_portal_format(self, processor):
        """Test parsing Portal date format - returns raw timestamp (not normalized)"""
        date_str = "2026-01-07T00:00:00+00:00"
        result = processor._parse_date(date_str)
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 7
        # Should preserve original time
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0
        assert result.tzinfo == timezone.utc
    
    def test_parse_date_fax_format(self, processor):
        """Test parsing Fax date format - returns raw timestamp (not normalized)"""
        date_str = "2026-01-08T12:30:45+00:00"
        result = processor._parse_date(date_str)
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 8
        # Should preserve original time
        assert result.hour == 12
        assert result.minute == 30
        assert result.second == 45
        assert result.tzinfo == timezone.utc
    
    def test_parse_date_invalid_format(self, processor):
        """Test parsing invalid date format returns None"""
        date_str = "invalid-date"
        result = processor._parse_date(date_str)
        assert result is None
    
    def test_parse_date_empty_string(self, processor):
        """Test parsing empty string returns None"""
        result = processor._parse_date("")
        assert result is None
    
    def test_parse_date_none(self, processor):
        """Test parsing None returns None"""
        result = processor._parse_date(None)
        assert result is None
    
    def test_extract_submission_date_esmd(self, processor, esmd_payload, parsed_esmd):
        """Test extracting submission date from ESMD payload"""
        result = processor._extract_submission_date_from_payload(
            payload=esmd_payload,
            parsed=parsed_esmd,
            channel_type_id=3  # ESMD
        )
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 6
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 0
        assert result.tzinfo == timezone.utc
    
    def test_extract_submission_date_portal(self, processor, portal_payload, parsed_portal):
        """Test extracting submission date from Portal payload"""
        result = processor._extract_submission_date_from_payload(
            payload=portal_payload,
            parsed=parsed_portal,
            channel_type_id=1  # Portal
        )
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 7
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 0
        assert result.tzinfo == timezone.utc
    
    def test_extract_submission_date_fax(self, processor, fax_payload, parsed_fax):
        """Test extracting submission date from Fax payload at packet creation (uses submission_metadata.creationTime)"""
        result = processor._extract_submission_date_from_payload(
            payload=fax_payload,
            parsed=parsed_fax,
            channel_type_id=2  # Fax
        )
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 8
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 0
        assert result.tzinfo == timezone.utc
    
    def test_extract_submission_date_missing_esmd(self, processor):
        """Test extracting submission date when ESMD date is missing"""
        payload = {
            "decision_tracking_id": "test-esmd-123",
            "submission_metadata": {},  # No creationTime
            "documents": []
        }
        # Create parsed object with empty submission_metadata
        parsed = ParsedPayloadModel(
            decision_tracking_id="test-esmd-123",
            unique_id="test-esmd-123",
            message_type="ingest_file_package",
            esmd_transaction_id=None,
            submission_metadata={},  # Empty - no creationTime
            documents=[DocumentModel(
                document_unique_identifier="doc1",
                file_name="test.pdf",
                mime_type="application/pdf",
                file_size=1000,
                source_absolute_url="https://example.com/test.pdf"
            )]
        )
        result = processor._extract_submission_date_from_payload(
            payload=payload,
            parsed=parsed,
            channel_type_id=3  # ESMD
        )
        assert result is None
    
    def test_extract_submission_date_missing_portal(self, processor, parsed_portal):
        """Test extracting submission date when Portal date is missing"""
        payload = {
            "decision_tracking_id": "test-portal-123",
            "ocr": {},  # No fields
            "documents": []
        }
        result = processor._extract_submission_date_from_payload(
            payload=payload,
            parsed=parsed_portal,
            channel_type_id=1  # Portal
        )
        assert result is None
    
    def test_extract_submission_date_missing_fax(self, processor):
        """Test extracting submission date when Fax date is missing at packet creation"""
        payload = {
            "decision_tracking_id": "test-fax-123",
            "submission_metadata": {},  # No creationTime
            "documents": []
        }
        parsed = ParsedPayloadModel(
            decision_tracking_id="test-fax-123",
            unique_id="test-fax-123",
            message_type="ingest_file_package",
            esmd_transaction_id=None,
            submission_metadata={},  # Empty
            documents=[DocumentModel(
                document_unique_identifier="doc1",
                file_name="test.pdf",
                mime_type="application/pdf",
                file_size=1000,
                source_absolute_url="https://example.com/test.pdf"
            )]
        )
        result = processor._extract_submission_date_from_payload(
            payload=payload,
            parsed=parsed,
            channel_type_id=2  # Fax
        )
        assert result is None
    
    def test_extract_submission_date_unknown_channel(self, processor, esmd_payload, parsed_esmd):
        """Test extracting submission date with unknown channel type"""
        result = processor._extract_submission_date_from_payload(
            payload=esmd_payload,
            parsed=parsed_esmd,
            channel_type_id=99  # Unknown channel
        )
        assert result is None
    
    def test_extract_submission_date_none_channel(self, processor, esmd_payload, parsed_esmd):
        """Test extracting submission date with None channel type"""
        result = processor._extract_submission_date_from_payload(
            payload=esmd_payload,
            parsed=parsed_esmd,
            channel_type_id=None
        )
        assert result is None
    
    def test_calculate_due_date_standard(self, processor):
        """Test calculating due date for Standard submission (72 hours)"""
        received_date = datetime(2026, 1, 6, 0, 0, 0, tzinfo=timezone.utc)
        due_date = processor._calculate_due_date(received_date, submission_type="Standard")
        
        # Standard is 72 hours = 3 days
        assert due_date.year == 2026
        assert due_date.month == 1
        assert due_date.day == 9  # 6 + 3 days
        assert due_date.hour == 0
        assert due_date.minute == 0
        assert due_date.second == 0
        assert due_date.microsecond == 0
        assert due_date.tzinfo == timezone.utc
    
    def test_calculate_due_date_expedited(self, processor):
        """Test calculating due date for Expedited submission (48 hours)"""
        received_date = datetime(2026, 1, 6, 0, 0, 0, tzinfo=timezone.utc)
        due_date = processor._calculate_due_date(received_date, submission_type="Expedited")
        
        # Expedited is 48 hours = 2 days
        assert due_date.year == 2026
        assert due_date.month == 1
        assert due_date.day == 8  # 6 + 2 days
        assert due_date.hour == 0
        assert due_date.minute == 0
        assert due_date.second == 0
        assert due_date.microsecond == 0
        assert due_date.tzinfo == timezone.utc
    
    def test_calculate_due_date_default_standard(self, processor):
        """Test calculating due date with no submission type (defaults to Standard)"""
        received_date = datetime(2026, 1, 6, 0, 0, 0, tzinfo=timezone.utc)
        due_date = processor._calculate_due_date(received_date, submission_type=None)
        
        # Should default to Standard (72 hours = 3 days)
        assert due_date.year == 2026
        assert due_date.month == 1
        assert due_date.day == 9  # 6 + 3 days
        assert due_date.hour == 0
        assert due_date.minute == 0
        assert due_date.second == 0
        assert due_date.microsecond == 0
        assert due_date.tzinfo == timezone.utc
    
    def test_calculate_due_date_timezone_aware(self, processor):
        """Test calculating due date with timezone-aware datetime"""
        received_date = datetime(2026, 1, 6, 14, 30, 0, tzinfo=timezone.utc)
        due_date = processor._calculate_due_date(received_date, submission_type="Standard")
        
        # Should normalize to midnight
        assert due_date.year == 2026
        assert due_date.month == 1
        assert due_date.day == 9  # 6 + 3 days (normalized to midnight)
        assert due_date.hour == 0
        assert due_date.minute == 0
        assert due_date.second == 0
        assert due_date.microsecond == 0
        assert due_date.tzinfo == timezone.utc
    
    def test_calculate_due_date_timezone_naive(self, processor):
        """Test calculating due date with timezone-naive datetime (should convert to UTC)"""
        received_date = datetime(2026, 1, 6, 0, 0, 0)  # No timezone
        due_date = processor._calculate_due_date(received_date, submission_type="Standard")
        
        # Should convert to UTC and normalize to midnight
        assert due_date.year == 2026
        assert due_date.month == 1
        assert due_date.day == 9  # 6 + 3 days
        assert due_date.hour == 0
        assert due_date.minute == 0
        assert due_date.second == 0
        assert due_date.microsecond == 0
        assert due_date.tzinfo == timezone.utc
    
    def test_fax_extraction_at_creation_uses_submission_metadata(self, processor, fax_payload, parsed_fax):
        """Test that Fax channel uses submission_metadata.creationTime at packet creation"""
        result = processor._extract_submission_date_from_payload(
            payload=fax_payload,
            parsed=parsed_fax,
            channel_type_id=2  # Fax
        )
        
        # Should extract from submission_metadata.creationTime, not extracted_fields
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 8
        assert result.hour == 0  # Normalized to midnight
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 0
        assert result.tzinfo == timezone.utc
    
    def test_fax_post_ocr_update_from_extracted_fields(self, processor, fax_extracted_fields):
        """Test that Fax channel can update received_date from extracted_fields after OCR"""
        # Simulate extracted_fields after OCR
        extracted_fields = fax_extracted_fields
        fields = extracted_fields.get('fields', {})
        submitted_date_field = fields.get('Submitted Date', {})
        submission_date_str = submitted_date_field.get('value')
        
        # Parse (returns raw timestamp, not normalized)
        result = processor._parse_date(submission_date_str)
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 8
        # Should preserve original time (not normalized to midnight)
        # The exact time depends on the test data, but it should be preserved
        assert result.tzinfo == timezone.utc

