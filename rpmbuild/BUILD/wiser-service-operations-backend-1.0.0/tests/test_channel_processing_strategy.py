"""
Unit tests for Channel Processing Strategy Pattern
Tests all three channel strategies and factory function
"""
import pytest
from unittest.mock import MagicMock

from app.models.channel_type import ChannelType
from app.services.channel_processing_strategy import (
    ChannelProcessingStrategy,
    ESMDProcessingStrategy,
    GenzeonFaxProcessingStrategy,
    GenzeonPortalProcessingStrategy,
    get_channel_strategy
)
from app.services.document_splitter import SplitResult, SplitPage


class TestESMDProcessingStrategy:
    """Test ESMDProcessingStrategy"""
    
    @pytest.fixture
    def strategy(self):
        """Create ESMDProcessingStrategy instance"""
        return ESMDProcessingStrategy()
    
    def test_should_run_ocr(self, strategy):
        """Test ESMD should run OCR"""
        assert strategy.should_run_ocr() is True
    
    def test_extract_fields_from_payload_raises_error(self, strategy):
        """Test ESMD does not extract from payload"""
        payload = {"documents": []}
        split_result = MagicMock()
        
        with pytest.raises(NotImplementedError) as exc_info:
            strategy.extract_fields_from_payload(payload, split_result)
        
        assert "ESMDProcessingStrategy does not extract fields from payload" in str(exc_info.value)
    
    def test_get_coversheet_page_number_returns_default(self, strategy):
        """Test ESMD get_coversheet_page_number returns default"""
        payload = {"documents": []}
        split_result = MagicMock()
        
        page_num = strategy.get_coversheet_page_number(payload, split_result)
        assert page_num == 1
    
    def test_get_part_type_returns_default(self, strategy):
        """Test ESMD get_part_type returns default"""
        payload = {"documents": []}
        
        part_type = strategy.get_part_type(payload)
        assert part_type == "UNKNOWN"


class TestGenzeonFaxProcessingStrategy:
    """Test GenzeonFaxProcessingStrategy"""
    
    @pytest.fixture
    def strategy(self):
        """Create GenzeonFaxProcessingStrategy instance"""
        return GenzeonFaxProcessingStrategy()
    
    def test_should_run_ocr(self, strategy):
        """Test Genzeon Fax should run OCR"""
        assert strategy.should_run_ocr() is True
    
    def test_extract_fields_from_payload_raises_error(self, strategy):
        """Test Genzeon Fax does not extract from payload"""
        payload = {"documents": []}
        split_result = MagicMock()
        
        with pytest.raises(NotImplementedError) as exc_info:
            strategy.extract_fields_from_payload(payload, split_result)
        
        assert "GenzeonFaxProcessingStrategy does not extract fields from payload" in str(exc_info.value)
    
    def test_get_coversheet_page_number_returns_default(self, strategy):
        """Test Genzeon Fax get_coversheet_page_number returns default"""
        payload = {"documents": []}
        split_result = MagicMock()
        
        page_num = strategy.get_coversheet_page_number(payload, split_result)
        assert page_num == 1
    
    def test_get_part_type_returns_default(self, strategy):
        """Test Genzeon Fax get_part_type returns default"""
        payload = {"documents": []}
        
        part_type = strategy.get_part_type(payload)
        assert part_type == "UNKNOWN"


class TestGenzeonPortalProcessingStrategy:
    """Test GenzeonPortalProcessingStrategy"""
    
    @pytest.fixture
    def strategy(self):
        """Create GenzeonPortalProcessingStrategy instance"""
        return GenzeonPortalProcessingStrategy()
    
    @pytest.fixture
    def sample_portal_payload(self):
        """Sample Genzeon Portal payload with ocr field"""
        return {
            "documents": [{"blobPath": "container/portal/test.pdf"}],
            "decision_tracking_id": "test-uuid",
            "ocr": {
                "fields": {
                    "Beneficiary First Name": {
                        "value": "MICHAEL",
                        "confidence": 1,
                        "field_type": "DocumentFieldType.STRING"
                    },
                    "Beneficiary Last Name": {
                        "value": "MASI",
                        "confidence": 1,
                        "field_type": "DocumentFieldType.STRING"
                    },
                    "Provider NPI": {
                        "value": "1619025038",
                        "confidence": 1,
                        "field_type": "DocumentFieldType.STRING"
                    }
                },
                "doc_type": "coversheet-extraction",
                "model_id": "coversheet-extraction",
                "coversheet_type": "Genzeon Portal Prior Authorization Request...",
                "overall_document_confidence": 0.999
            }
        }
    
    @pytest.fixture
    def sample_split_result(self):
        """Sample SplitResult for testing"""
        pages = [
            SplitPage(
                page_number=1,
                local_path="/tmp/page_1.pdf",
                dest_blob_path="page_1.pdf",
                file_size_bytes=1000
            ),
            SplitPage(
                page_number=2,
                local_path="/tmp/page_2.pdf",
                dest_blob_path="page_2.pdf",
                file_size_bytes=2000
            )
        ]
        return SplitResult(
            processing_path="test/processing",
            page_count=2,
            pages=pages,
            local_paths=["/tmp/page_1.pdf", "/tmp/page_2.pdf"]
        )
    
    def test_should_run_ocr(self, strategy):
        """Test Genzeon Portal should NOT run OCR"""
        assert strategy.should_run_ocr() is False
    
    def test_extract_fields_from_payload_success(
        self,
        strategy,
        sample_portal_payload,
        sample_split_result
    ):
        """Test successful field extraction from Portal payload"""
        extracted = strategy.extract_fields_from_payload(
            sample_portal_payload,
            sample_split_result
        )
        
        # Verify structure matches OCR output format
        assert 'fields' in extracted
        assert 'coversheet_type' in extracted
        assert 'doc_type' in extracted
        assert 'overall_document_confidence' in extracted
        assert 'duration_ms' in extracted
        assert 'page_number' in extracted
        assert 'raw' in extracted
        assert 'source' in extracted
        
        # Verify fields are normalized
        assert extracted['fields']['Beneficiary First Name']['value'] == "MICHAEL"
        assert extracted['fields']['Beneficiary First Name']['confidence'] == 1.0  # int->float
        assert extracted['fields']['Beneficiary First Name']['field_type'] == "STRING"  # normalized
        
        # Verify metadata
        assert extracted['coversheet_type'] == "Genzeon Portal Prior Authorization Request..."
        assert extracted['doc_type'] == "coversheet-extraction"
        assert extracted['overall_document_confidence'] == 0.999
        assert extracted['source'] == "PAYLOAD_INITIAL"
    
    def test_extract_fields_from_payload_missing_ocr(self, strategy, sample_split_result):
        """Test extraction fails when ocr field is missing"""
        payload = {"documents": []}
        
        with pytest.raises(ValueError) as exc_info:
            strategy.extract_fields_from_payload(payload, sample_split_result)
        
        assert "missing 'ocr' object" in str(exc_info.value).lower()
    
    def test_extract_fields_from_payload_missing_fields(
        self,
        strategy,
        sample_split_result
    ):
        """Test extraction fails when ocr.fields is missing"""
        payload = {
            "documents": [],
            "ocr": {}  # Missing fields
        }
        
        with pytest.raises(ValueError) as exc_info:
            strategy.extract_fields_from_payload(payload, sample_split_result)
        
        # The error message should mention missing fields
        error_msg = str(exc_info.value).lower()
        assert "missing" in error_msg and ("fields" in error_msg or "ocr" in error_msg)
    
    def test_extract_fields_from_payload_normalizes_confidence(
        self,
        strategy,
        sample_portal_payload,
        sample_split_result
    ):
        """Test confidence is normalized from int to float"""
        # Set confidence as int
        sample_portal_payload['ocr']['fields']['Test Field'] = {
            "value": "test",
            "confidence": 1,  # int
            "field_type": "DocumentFieldType.STRING"
        }
        
        extracted = strategy.extract_fields_from_payload(
            sample_portal_payload,
            sample_split_result
        )
        
        assert isinstance(extracted['fields']['Test Field']['confidence'], float)
        assert extracted['fields']['Test Field']['confidence'] == 1.0
    
    def test_extract_fields_from_payload_normalizes_field_type(
        self,
        strategy,
        sample_portal_payload,
        sample_split_result
    ):
        """Test field_type is normalized (removes DocumentFieldType. prefix)"""
        sample_portal_payload['ocr']['fields']['Test Field'] = {
            "value": "test",
            "confidence": 1,
            "field_type": "DocumentFieldType.STRING"
        }
        
        extracted = strategy.extract_fields_from_payload(
            sample_portal_payload,
            sample_split_result
        )
        
        assert extracted['fields']['Test Field']['field_type'] == "STRING"
    
    def test_extract_fields_from_payload_handles_null_values(
        self,
        strategy,
        sample_portal_payload,
        sample_split_result
    ):
        """Test extraction handles null field values"""
        sample_portal_payload['ocr']['fields']['Null Field'] = {
            "value": None,
            "confidence": 1,
            "field_type": "DocumentFieldType.STRING"
        }
        
        extracted = strategy.extract_fields_from_payload(
            sample_portal_payload,
            sample_split_result
        )
        
        assert extracted['fields']['Null Field']['value'] == ""
    
    def test_get_coversheet_page_number_from_payload(
        self,
        strategy,
        sample_portal_payload,
        sample_split_result
    ):
        """Test get_coversheet_page_number reads from payload"""
        sample_portal_payload['ocr']['coversheet_page_number'] = 2
        
        page_num = strategy.get_coversheet_page_number(sample_portal_payload, sample_split_result)
        assert page_num == 2
    
    def test_get_coversheet_page_number_defaults_to_one(
        self,
        strategy,
        sample_portal_payload
    ):
        """Test get_coversheet_page_number defaults to 1 if not in payload"""
        # Remove coversheet_page_number
        if 'coversheet_page_number' in sample_portal_payload['ocr']:
            del sample_portal_payload['ocr']['coversheet_page_number']
        
        split_result = MagicMock()
        page_num = strategy.get_coversheet_page_number(sample_portal_payload, split_result)
        assert page_num == 1
    
    def test_get_coversheet_page_number_validates_against_max_pages(
        self,
        strategy,
        sample_portal_payload,
        sample_split_result
    ):
        """Test get_coversheet_page_number validates against split_result max pages"""
        sample_portal_payload['ocr']['coversheet_page_number'] = 10  # Exceeds max pages (2)
        
        page_num = strategy.get_coversheet_page_number(sample_portal_payload, sample_split_result)
        # Should default to 1 when exceeds max
        assert page_num == 1
    
    def test_get_part_type_from_payload(self, strategy, sample_portal_payload):
        """Test get_part_type reads from payload.ocr.part_type directly"""
        sample_portal_payload['ocr']['part_type'] = "PART_A"
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "PART_A"
    
    def test_get_part_type_case_insensitive(self, strategy, sample_portal_payload):
        """Test get_part_type is case insensitive for direct part_type field"""
        sample_portal_payload['ocr']['part_type'] = "part_b"  # lowercase
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "PART_B"
    
    def test_get_part_type_uses_partclassifier_when_part_type_missing(
        self, strategy, sample_portal_payload
    ):
        """Test get_part_type uses PartClassifier when part_type field is missing"""
        # Remove part_type if it exists
        sample_portal_payload['ocr'].pop('part_type', None)
        # Set coversheet_type with "Medicare Part B"
        sample_portal_payload['ocr']['coversheet_type'] = (
            "Prior Authorization Request for Medicare Part B Services"
        )
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "PART_B"
    
    def test_get_part_type_uses_partclassifier_for_part_a(
        self, strategy, sample_portal_payload
    ):
        """Test get_part_type uses PartClassifier to detect Part A"""
        # Remove part_type if it exists
        sample_portal_payload['ocr'].pop('part_type', None)
        # Set coversheet_type with "Medicare Part A"
        sample_portal_payload['ocr']['coversheet_type'] = (
            "Prior Authorization Request for Medicare Part A Services"
        )
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "PART_A"
    
    def test_get_part_type_prioritizes_direct_field_over_classifier(
        self, strategy, sample_portal_payload
    ):
        """Test get_part_type prioritizes payload.ocr.part_type over PartClassifier"""
        # Set direct part_type field
        sample_portal_payload['ocr']['part_type'] = "PART_A"
        # Set coversheet_type that would classify as Part B
        sample_portal_payload['ocr']['coversheet_type'] = (
            "Prior Authorization Request for Medicare Part B Services"
        )
        
        part_type = strategy.get_part_type(sample_portal_payload)
        # Should use direct field, not classifier
        assert part_type == "PART_A"
    
    def test_get_part_type_handles_missing_ocr(self, strategy):
        """Test get_part_type handles missing ocr field"""
        payload = {"documents": []}
        
        part_type = strategy.get_part_type(payload)
        assert part_type == "UNKNOWN"
    
    def test_get_part_type_handles_ocr_not_dict(self, strategy):
        """Test get_part_type handles ocr that is not a dictionary"""
        payload = {"ocr": "not a dict"}
        
        part_type = strategy.get_part_type(payload)
        assert part_type == "UNKNOWN"
    
    def test_get_part_type_handles_empty_coversheet_type(
        self, strategy, sample_portal_payload
    ):
        """Test get_part_type handles empty coversheet_type"""
        sample_portal_payload['ocr'].pop('part_type', None)
        sample_portal_payload['ocr']['coversheet_type'] = ""
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "UNKNOWN"
    
    def test_get_part_type_handles_missing_coversheet_type(
        self, strategy, sample_portal_payload
    ):
        """Test get_part_type handles missing coversheet_type"""
        sample_portal_payload['ocr'].pop('part_type', None)
        sample_portal_payload['ocr'].pop('coversheet_type', None)
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "UNKNOWN"
    
    def test_get_part_type_handles_partclassifier_exception(
        self, strategy, sample_portal_payload, monkeypatch
    ):
        """Test get_part_type handles PartClassifier exceptions gracefully"""
        from app.services.part_classifier import PartClassifier
        
        # Create a mock that raises exception
        def mock_classify_part_type(ocr_result):
            raise Exception("Test error")
        
        # Patch PartClassifier.classify_part_type to raise exception
        original_classify = PartClassifier.classify_part_type
        PartClassifier.classify_part_type = mock_classify_part_type
        
        try:
            sample_portal_payload['ocr'].pop('part_type', None)
            sample_portal_payload['ocr']['coversheet_type'] = "Medicare Part B"
            
            part_type = strategy.get_part_type(sample_portal_payload)
            # Should return UNKNOWN on exception
            assert part_type == "UNKNOWN"
        finally:
            # Restore original method
            PartClassifier.classify_part_type = original_classify
    
    def test_get_part_type_handles_various_field_name_variations(
        self, strategy, sample_portal_payload
    ):
        """Test get_part_type handles various part_type field name variations"""
        # Test partType (camelCase)
        sample_portal_payload['ocr'].pop('part_type', None)
        sample_portal_payload['ocr']['partType'] = "PART_B"
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "PART_B"
        
        # Test part_type_classification
        sample_portal_payload['ocr'].pop('partType', None)
        sample_portal_payload['ocr']['part_type_classification'] = "PART_A"
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "PART_A"
    
    def test_get_part_type_real_world_scenario_part_b(
        self, strategy, sample_portal_payload
    ):
        """Test get_part_type with real-world Portal scenario: Medicare Part B"""
        # Simulate real Portal payload: no part_type, but has coversheet_type
        sample_portal_payload['ocr'].pop('part_type', None)
        sample_portal_payload['ocr']['coversheet_type'] = (
            "Prior Authorization Request for Medicare Part B Services - "
            "This form is used to request prior authorization for Medicare Part B services"
        )
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "PART_B"
    
    def test_get_part_type_real_world_scenario_part_a(
        self, strategy, sample_portal_payload
    ):
        """Test get_part_type with real-world Portal scenario: Medicare Part A"""
        sample_portal_payload['ocr'].pop('part_type', None)
        sample_portal_payload['ocr']['coversheet_type'] = (
            "Prior Authorization Request for Medicare Part A Services"
        )
        
        part_type = strategy.get_part_type(sample_portal_payload)
        assert part_type == "PART_A"


class TestGetChannelStrategy:
    """Test factory function get_channel_strategy"""
    
    def test_get_strategy_for_portal(self):
        """Test factory returns GenzeonPortalProcessingStrategy for Portal"""
        strategy = get_channel_strategy(ChannelType.GENZEON_PORTAL)
        assert isinstance(strategy, GenzeonPortalProcessingStrategy)
    
    def test_get_strategy_for_fax(self):
        """Test factory returns GenzeonFaxProcessingStrategy for Fax"""
        strategy = get_channel_strategy(ChannelType.GENZEON_FAX)
        assert isinstance(strategy, GenzeonFaxProcessingStrategy)
    
    def test_get_strategy_for_esmd(self):
        """Test factory returns ESMDProcessingStrategy for ESMD"""
        strategy = get_channel_strategy(ChannelType.ESMD)
        assert isinstance(strategy, ESMDProcessingStrategy)
    
    def test_get_strategy_for_none_defaults_to_esmd(self):
        """Test factory defaults to ESMD for None (backward compatibility)"""
        strategy = get_channel_strategy(None)
        assert isinstance(strategy, ESMDProcessingStrategy)
    
    def test_get_strategy_for_zero_defaults_to_esmd(self):
        """Test factory defaults to ESMD for 0 (empty)"""
        strategy = get_channel_strategy(0)
        assert isinstance(strategy, ESMDProcessingStrategy)
    
    def test_get_strategy_for_unknown_defaults_to_esmd(self):
        """Test factory defaults to ESMD for unknown channel_type_id"""
        strategy = get_channel_strategy(999)  # Unknown ID
        assert isinstance(strategy, ESMDProcessingStrategy)

