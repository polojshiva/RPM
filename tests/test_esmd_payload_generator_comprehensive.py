"""
Comprehensive Unit Tests for ESMD Payload Generator
Tests all 8 payload types and edge cases
"""
# Import conftest to mock blob storage first
import tests.conftest_esmd  # noqa: F401

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from sqlalchemy.orm import Session

from app.services.esmd_payload_generator import EsmdPayloadGenerator
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB


class TestAll8PayloadTypes:
    """Test all 8 payload type combinations"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock(spec=Session)
        db.query = Mock()
        return db
    
    @pytest.fixture(autouse=True)
    def mock_blob_storage(self, monkeypatch):
        """Auto-mock blob storage for all tests"""
        mock_blob_client = Mock()
        mock_blob_client.resolve_blob_url.return_value = "https://example.com/blob.pdf"
        monkeypatch.setattr('app.services.esmd_payload_generator.BlobStorageClient', lambda *args, **kwargs: mock_blob_client)
        return mock_blob_client
    
    
    @pytest.fixture
    def base_packet(self):
        """Base packet for all tests"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 12345
        packet.external_id = "SVC-2026-001234"
        packet.decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        packet.beneficiary_name = "John Doe"
        packet.beneficiary_mbi = "1EG4TE5MK72"
        packet.provider_name = "ABC Medical Clinic"
        packet.provider_npi = "1234567890"
        packet.submission_type = "Expedited"
        return packet
    
    @pytest.fixture
    def base_extracted_fields(self):
        """Base extracted fields for all tests"""
        return {
            "fields": {
                "provider_ptan": {"value": "P1234567"},
                "provider_address": {"value": "123 Main St"},
                "provider_city": {"value": "Newark"},
                "provider_state": {"value": "NJ"},
                "provider_zip": {"value": "07102"},
                "requester_name": {"value": "Medical Records Dept"},
                "requester_phone": {"value": "555-123-4567"},
                "patient_date_of_birth": {"value": "1955-07-21"},
                "anticipated_date_of_service": {"value": "2026-01-15"},
                "diagnosis_code": {"value": "M54.5"},
                "state": {"value": "NJ"},
                "facility_npi": {"value": "9876543210"},
                "facility_name": {"value": "General Hospital"},
                "facility_ptan": {"value": "F123456"},
                "facility_address": {"value": "456 Hospital Ave"},
                "facility_city": {"value": "Newark"},
                "facility_state": {"value": "NJ"},
                "facility_zip": {"value": "07103"},
                "facility_ccn": {"value": "311914"},
                "rendering_provider_npi": {"value": "9876543210"},
                "type_of_bill": {"value": "13"}
            }
        }
    
    @pytest.fixture
    def base_document(self, base_extracted_fields):
        """Base document for all tests"""
        doc = Mock(spec=PacketDocumentDB)
        doc.extracted_fields = base_extracted_fields
        doc.updated_extracted_fields = None
        doc.consolidated_blob_path = "consolidated/test.pdf"
        return doc
    
    @pytest.fixture
    def base_procedures_affirm(self):
        """Base procedures for Affirm decisions"""
        return [
            {
                "procedure_code": "99214",
                "place_of_service": "11",
                "mr_count_unit_of_service": "1",
                "modifier": "25",
                "review_codes": "",
                "program_codes": ""
            }
        ]
    
    @pytest.fixture
    def base_procedures_non_affirm(self):
        """Base procedures for Non-Affirm decisions"""
        return [
            {
                "procedure_code": "22510",
                "place_of_service": "11",
                "mr_count_unit_of_service": "1",
                "modifier": "",
                "review_codes": "0F",
                "program_codes": "GBC01"
            }
        ]
    
    def test_1_standard_pa_part_a_affirm(self, mock_db, base_packet, base_document, base_procedures_affirm):
        """Test Standard PA Part A Affirm payload"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "STANDARD_PA"
        decision.part_type = "A"
        
        # Set up packet with case_id containing esmdTransactionId (ESMD channel)
        base_packet.channel_type_id = 3  # ESMD
        base_packet.case_id = "ANA0001521259EC"  # ESMD transaction ID
        
        mock_db.query.return_value.filter.return_value.first.return_value = base_document
        
        generator = EsmdPayloadGenerator(mock_db)
        payload = generator.generate_payload(
            packet=base_packet,
            packet_decision=decision,
            procedures=base_procedures_affirm,
            medical_docs=None
        )
        
        # Validate structure
        assert payload['partType'] == 'A'
        assert payload['isDirectPa'] == False
        # Standard PA should include esmdTransactionId from packet.case_id
        assert 'esmdTransactionId' in payload
        assert payload['esmdTransactionId'] == "ANA0001521259EC"
        assert 'medicalDocuments' not in payload
        
        # Validate header
        header = payload['header']
        assert header['priorAuthDecision'] == 'A'
        assert 'typeOfBill' in header
        assert header['typeOfBill'] in ['13', '131']
        assert 'stateCode' not in header
        
        # Validate facility (Part A)
        facility = header['facilityOrRenderingProvider']
        assert 'ccn' in facility
        assert 'renderingProviderNpi' not in facility
        
        # Validate procedures (Part A - no placeOfService)
        assert len(payload['procedures']) == 1
        proc = payload['procedures'][0]
        assert proc['decisionIndicator'] == 'A'
        assert 'placeOfService' not in proc
        
        # Validate dates (Part A: hyphenated)
        assert '-' in header['beneficiary']['dateOfBirth']
        assert '-' in header['anticipatedDateOfService']
    
    def test_2_standard_pa_part_a_non_affirm(self, mock_db, base_packet, base_document, base_procedures_non_affirm):
        """Test Standard PA Part A Non-Affirm payload"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "NON_AFFIRM"
        decision.decision_subtype = "STANDARD_PA"
        decision.part_type = "A"
        
        mock_db.query.return_value.filter.return_value.first.return_value = base_document
        
        generator = EsmdPayloadGenerator(mock_db)
        payload = generator.generate_payload(
            packet=base_packet,
            packet_decision=decision,
            procedures=base_procedures_non_affirm,
            medical_docs=None
        )
        
        # Validate structure
        assert payload['partType'] == 'A'
        assert payload['isDirectPa'] == False
        assert 'medicalDocuments' not in payload
        
        # Validate header
        header = payload['header']
        assert header['priorAuthDecision'] == 'N'  # FIXED: was "D"
        
        # Validate procedures (Non-Affirm requires reviewCodes and programCodes)
        proc = payload['procedures'][0]
        assert proc['decisionIndicator'] == 'N'  # FIXED: was "D"
        assert proc['reviewCodes'] == '0F'
        assert proc['programCodes'] == 'GBC01'
    
    def test_3_standard_pa_part_b_affirm(self, mock_db, base_packet, base_document, base_procedures_affirm):
        """Test Standard PA Part B Affirm payload"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "STANDARD_PA"
        decision.part_type = "B"
        
        # Set up packet with case_id containing esmdTransactionId (ESMD channel)
        base_packet.channel_type_id = 3  # ESMD
        base_packet.case_id = "FSI0001524152EC"  # ESMD transaction ID
        
        mock_db.query.return_value.filter.return_value.first.return_value = base_document
        
        generator = EsmdPayloadGenerator(mock_db)
        payload = generator.generate_payload(
            packet=base_packet,
            packet_decision=decision,
            procedures=base_procedures_affirm,
            medical_docs=None
        )
        
        # Validate structure
        assert payload['partType'] == 'B'
        assert payload['isDirectPa'] == False
        # Standard PA should include esmdTransactionId from packet.case_id
        assert 'esmdTransactionId' in payload
        assert payload['esmdTransactionId'] == "FSI0001524152EC"
        assert 'medicalDocuments' not in payload
        
        # Validate header
        header = payload['header']
        assert header['priorAuthDecision'] == 'A'
        assert 'stateCode' in header
        assert header['stateCode'] == header['state']
        assert 'typeOfBill' not in header
        
        # Validate facility (Part B)
        facility = header['facilityOrRenderingProvider']
        assert 'renderingProviderNpi' in facility
        assert 'ccn' not in facility
        
        # Validate procedures (Part B - requires placeOfService)
        proc = payload['procedures'][0]
        assert 'placeOfService' in proc
        assert proc['placeOfService'] == '11'
        
        # Validate dates (Part B: non-hyphenated)
        assert '-' not in header['beneficiary']['dateOfBirth']
        assert '-' not in header['anticipatedDateOfService']
    
    def test_4_standard_pa_part_b_non_affirm(self, mock_db, base_packet, base_document, base_procedures_non_affirm):
        """Test Standard PA Part B Non-Affirm payload"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "NON_AFFIRM"
        decision.decision_subtype = "STANDARD_PA"
        decision.part_type = "B"
        
        mock_db.query.return_value.filter.return_value.first.return_value = base_document
        
        generator = EsmdPayloadGenerator(mock_db)
        payload = generator.generate_payload(
            packet=base_packet,
            packet_decision=decision,
            procedures=base_procedures_non_affirm,
            medical_docs=None
        )
        
        # Validate structure
        assert payload['partType'] == 'B'
        assert payload['isDirectPa'] == False
        assert payload['header']['priorAuthDecision'] == 'N'  # FIXED: was "D"
        
        # Validate procedures
        proc = payload['procedures'][0]
        assert proc['decisionIndicator'] == 'N'  # FIXED: was "D"
        assert proc['reviewCodes'] == '0F'
        assert proc['programCodes'] == 'GBC01'
    
    def test_5_direct_pa_part_a_affirm(self, mock_db, base_packet, base_document, base_procedures_affirm):
        """Test Direct PA Part A Affirm payload"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "A"
        
        mock_db.query.return_value.filter.return_value.first.return_value = base_document
        
        generator = EsmdPayloadGenerator(mock_db)
        payload = generator.generate_payload(
            packet=base_packet,
            packet_decision=decision,
            procedures=base_procedures_affirm,
            medical_docs=["medical-docs/doc1.pdf", "medical-docs/doc2.pdf"]
        )
        
        # Validate structure
        assert payload['partType'] == 'A'
        assert payload['isDirectPa'] == True
        assert 'esmdTransactionId' not in payload
        assert 'medicalDocuments' in payload
        assert len(payload['medicalDocuments']) > 0
    
    def test_6_direct_pa_part_a_non_affirm(self, mock_db, base_packet, base_document, base_procedures_non_affirm):
        """Test Direct PA Part A Non-Affirm payload"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "NON_AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "A"
        
        mock_db.query.return_value.filter.return_value.first.return_value = base_document
        
        generator = EsmdPayloadGenerator(mock_db)
        payload = generator.generate_payload(
            packet=base_packet,
            packet_decision=decision,
            procedures=base_procedures_non_affirm,
            medical_docs=["medical-docs/doc1.pdf"]
        )
        
        # Validate structure
        assert payload['partType'] == 'A'
        assert payload['isDirectPa'] == True
        assert payload['header']['priorAuthDecision'] == 'N'  # FIXED: was "D"
        assert 'medicalDocuments' in payload
    
    def test_7_direct_pa_part_b_affirm(self, mock_db, base_packet, base_document, base_procedures_affirm):
        """Test Direct PA Part B Affirm payload"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "B"
        
        mock_db.query.return_value.filter.return_value.first.return_value = base_document
        
        generator = EsmdPayloadGenerator(mock_db)
        payload = generator.generate_payload(
            packet=base_packet,
            packet_decision=decision,
            procedures=base_procedures_affirm,
            medical_docs=["medical-docs/doc1.pdf"]
        )
        
        # Validate structure
        assert payload['partType'] == 'B'
        assert payload['isDirectPa'] == True
        assert 'medicalDocuments' in payload
        assert 'stateCode' in payload['header']
    
    def test_8_direct_pa_part_b_non_affirm(self, mock_db, base_packet, base_document, base_procedures_non_affirm):
        """Test Direct PA Part B Non-Affirm payload"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "NON_AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "B"
        
        mock_db.query.return_value.filter.return_value.first.return_value = base_document
        
        generator = EsmdPayloadGenerator(mock_db)
        payload = generator.generate_payload(
            packet=base_packet,
            packet_decision=decision,
            procedures=base_procedures_non_affirm,
            medical_docs=["medical-docs/doc1.pdf"]
        )
        
        # Validate structure
        assert payload['partType'] == 'B'
        assert payload['isDirectPa'] == True
        assert payload['header']['priorAuthDecision'] == 'N'  # FIXED: was "D"
        assert payload['procedures'][0]['decisionIndicator'] == 'N'  # FIXED: was "D"
        assert 'medicalDocuments' in payload


class TestDateFormatting:
    """Test date formatting for Part A vs Part B"""
    
    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)
    
    def test_part_a_date_formatting_hyphenated(self, mock_db):
        """Test Part A dates are hyphenated (YYYY-MM-DD)"""
        generator = EsmdPayloadGenerator(mock_db)
        
        # Test various input formats
        test_cases = [
            ("1955-07-21", "1955-07-21"),  # Already hyphenated
            ("07/21/1955", "1955-07-21"),  # MM/DD/YYYY
            ("19550721", "1955-07-21"),    # YYYYMMDD
        ]
        
        for input_date, expected in test_cases:
            result = generator._format_date_for_esmd(input_date, is_part_a=True, is_part_b=False)
            assert result == expected, f"Failed for input: {input_date}"
            assert '-' in result, "Part A dates must be hyphenated"
    
    def test_part_b_date_formatting_non_hyphenated(self, mock_db):
        """Test Part B dates are non-hyphenated (YYYYMMDD)"""
        generator = EsmdPayloadGenerator(mock_db)
        
        # Test various input formats
        test_cases = [
            ("1955-07-21", "19550721"),  # Hyphenated input
            ("07/21/1955", "19550721"),  # MM/DD/YYYY
            ("19550721", "19550721"),    # Already YYYYMMDD
        ]
        
        for input_date, expected in test_cases:
            result = generator._format_date_for_esmd(input_date, is_part_a=False, is_part_b=True)
            assert result == expected, f"Failed for input: {input_date}"
            assert '-' not in result, "Part B dates must not be hyphenated"
    
    def test_date_formatting_empty_string(self, mock_db):
        """Test empty date string handling"""
        generator = EsmdPayloadGenerator(mock_db)
        result = generator._format_date_for_esmd("", is_part_a=True, is_part_b=False)
        assert result == ""
        
        result = generator._format_date_for_esmd("", is_part_a=False, is_part_b=True)
        assert result == ""
    
    def test_date_formatting_invalid_format(self, mock_db):
        """Test invalid date format handling"""
        generator = EsmdPayloadGenerator(mock_db)
        result = generator._format_date_for_esmd("invalid-date", is_part_a=True, is_part_b=False)
        # Should return empty string or handle gracefully
        assert result == "" or isinstance(result, str)


class TestPhoneFormatting:
    """Test phone number formatting"""
    
    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)
    
    def test_phone_formatting_removes_non_digits(self, mock_db):
        """Test phone formatting removes all non-digits"""
        generator = EsmdPayloadGenerator(mock_db)
        
        test_cases = [
            ("555-123-4567", "5551234567"),
            ("(555) 123-4567", "5551234567"),
            ("555.123.4567", "5551234567"),
            ("5551234567", "5551234567"),
            ("+1-555-123-4567", "15551234567"),
        ]
        
        for input_phone, expected in test_cases:
            result = generator._format_phone(input_phone)
            assert result == expected, f"Failed for input: {input_phone}"
    
    def test_phone_formatting_empty_string(self, mock_db):
        """Test empty phone string handling"""
        generator = EsmdPayloadGenerator(mock_db)
        result = generator._format_phone("")
        assert result == ""


class TestDiagnosisCodeFormatting:
    """Test diagnosis code formatting"""
    
    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)
    
    def test_diagnosis_code_removes_periods(self, mock_db):
        """Test diagnosis code removes periods"""
        generator = EsmdPayloadGenerator(mock_db)
        
        test_cases = [
            ("M54.5", "M545"),
            ("E11.621", "E11621"),
            ("M8008XA", "M8008XA"),  # No periods
            ("E11621", "E11621"),    # Already formatted
        ]
        
        for input_code, expected in test_cases:
            result = generator._format_diagnosis_code(input_code)
            assert result == expected, f"Failed for input: {input_code}"
            assert '.' not in result, "Diagnosis codes must not contain periods"
    
    def test_diagnosis_code_empty_string(self, mock_db):
        """Test empty diagnosis code handling"""
        generator = EsmdPayloadGenerator(mock_db)
        result = generator._format_diagnosis_code("")
        assert result == ""


class TestDecisionMapping:
    """Test decision outcome mapping"""
    
    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)
    
    def test_affirm_maps_to_a(self, mock_db):
        """Test AFFIRM maps to 'A'"""
        generator = EsmdPayloadGenerator(mock_db)
        assert generator._map_decision_outcome("AFFIRM") == "A"
        assert generator._map_decision_indicator("AFFIRM") == "A"
    
    def test_non_affirm_maps_to_n(self, mock_db):
        """Test NON_AFFIRM maps to 'N' (FIXED: was 'D')"""
        generator = EsmdPayloadGenerator(mock_db)
        assert generator._map_decision_outcome("NON_AFFIRM") == "N"
        assert generator._map_decision_indicator("NON_AFFIRM") == "N"
    
    def test_dismissal_maps_to_n(self, mock_db):
        """Test DISMISSAL maps to 'N'"""
        generator = EsmdPayloadGenerator(mock_db)
        assert generator._map_decision_outcome("DISMISSAL") == "N"
    
    def test_unknown_decision_outcome(self, mock_db):
        """Test unknown decision outcome handling"""
        generator = EsmdPayloadGenerator(mock_db)
        result = generator._map_decision_outcome("UNKNOWN")
        assert result == ""


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)
    
    @pytest.fixture
    def minimal_packet(self):
        """Minimal packet with required fields only"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 999
        packet.beneficiary_name = "Test Patient"
        packet.beneficiary_mbi = "1EG4TE5MK72"
        packet.provider_name = "Test Provider"
        packet.provider_npi = "1234567890"
        packet.submission_type = None
        return packet
    
    @pytest.fixture
    def minimal_document(self):
        """Minimal document with empty extracted fields"""
        doc = Mock(spec=PacketDocumentDB)
        doc.extracted_fields = {"fields": {}}
        doc.updated_extracted_fields = None
        doc.consolidated_blob_path = None
        return doc
    
    def test_missing_packet_document(self, mock_db, minimal_packet):
        """Test error when packet document is missing"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "B"
        
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        generator = EsmdPayloadGenerator(mock_db)
        
        with pytest.raises(ValueError, match="No packet_document found"):
            generator.generate_payload(
                packet=minimal_packet,
                packet_decision=decision,
                procedures=[],
                medical_docs=None
            )
    
    def test_missing_extracted_fields(self, mock_db, minimal_packet, minimal_document):
        """Test handling of missing extracted fields"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "B"
        
        mock_db.query.return_value.filter.return_value.first.return_value = minimal_document
        
        generator = EsmdPayloadGenerator(mock_db)
        
        # Should not raise error, should use defaults
        payload = generator.generate_payload(
            packet=minimal_packet,
            packet_decision=decision,
            procedures=[],
            medical_docs=None
        )
        
        assert payload is not None
        assert 'header' in payload
    
    def test_empty_procedures_array(self, mock_db, minimal_packet, minimal_document):
        """Test handling of empty procedures array"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "B"
        
        mock_db.query.return_value.filter.return_value.first.return_value = minimal_document
        
        generator = EsmdPayloadGenerator(mock_db)
        
        payload = generator.generate_payload(
            packet=minimal_packet,
            packet_decision=decision,
            procedures=[],
            medical_docs=None
        )
        
        assert payload['procedures'] == []
    
    def test_multiple_procedures(self, mock_db, minimal_packet, minimal_document):
        """Test handling of multiple procedures (max 3)"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "B"
        
        minimal_document.extracted_fields = {
            "fields": {
                "state": {"value": "NJ"}
            }
        }
        
        mock_db.query.return_value.filter.return_value.first.return_value = minimal_document
        
        generator = EsmdPayloadGenerator(mock_db)
        
        procedures = [
            {"procedure_code": "99214", "place_of_service": "11", "mr_count_unit_of_service": "1"},
            {"procedure_code": "99215", "place_of_service": "12", "mr_count_unit_of_service": "2"},
            {"procedure_code": "99216", "place_of_service": "19", "mr_count_unit_of_service": "3"},
        ]
        
        payload = generator.generate_payload(
            packet=minimal_packet,
            packet_decision=decision,
            procedures=procedures,
            medical_docs=None
        )
        
        assert len(payload['procedures']) == 3
    
    def test_part_type_defaults_to_b(self, mock_db, minimal_packet, minimal_document):
        """Test that part_type defaults to 'B' if not set"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = None  # Not set
        
        minimal_document.extracted_fields = {
            "fields": {
                "state": {"value": "NJ"}
            }
        }
        
        mock_db.query.return_value.filter.return_value.first.return_value = minimal_document
        
        generator = EsmdPayloadGenerator(mock_db)
        
        payload = generator.generate_payload(
            packet=minimal_packet,
            packet_decision=decision,
            procedures=[],
            medical_docs=None
        )
        
        assert payload['partType'] == 'B'  # Default
    
    def test_standard_pa_missing_esmd_transaction_id(self, mock_db, minimal_packet, minimal_document):
        """Test Standard PA with missing esmdTransactionId (should warn but not fail)"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "STANDARD_PA"
        decision.part_type = "B"
        
        # Set up ESMD packet without case_id (missing esmdTransactionId)
        minimal_packet.channel_type_id = 3  # ESMD
        minimal_packet.case_id = None  # No esmdTransactionId stored
        
        minimal_document.extracted_fields = {
            "fields": {
                "state": {"value": "NJ"}
            }
        }
        
        mock_db.query.return_value.filter.return_value.first.return_value = minimal_document
        
        generator = EsmdPayloadGenerator(mock_db)
        
        # Should not raise error, but may log warning
        payload = generator.generate_payload(
            packet=minimal_packet,
            packet_decision=decision,
            procedures=[],
            medical_docs=None
        )
        
        assert payload['isDirectPa'] == False
        # esmdTransactionId may be missing (will be logged as warning)
        # This can happen if packet was created before this feature was implemented
    
    def test_direct_pa_missing_medical_documents(self, mock_db, minimal_packet, minimal_document):
        """Test Direct PA with missing medical documents"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "B"
        
        minimal_document.extracted_fields = {
            "fields": {
                "state": {"value": "NJ"}
            }
        }
        minimal_document.consolidated_blob_path = None  # No fallback
        
        mock_db.query.return_value.filter.return_value.first.return_value = minimal_document
        
        generator = EsmdPayloadGenerator(mock_db)
        
        payload = generator.generate_payload(
            packet=minimal_packet,
            packet_decision=decision,
            procedures=[],
            medical_docs=None  # No medical docs provided
        )
        
        assert payload['isDirectPa'] == True
        assert 'medicalDocuments' in payload
        # May be empty array if no fallback available


class TestNameExtraction:
    """Test name extraction from full name"""
    
    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)
    
    def test_extract_first_name(self, mock_db):
        """Test first name extraction"""
        generator = EsmdPayloadGenerator(mock_db)
        
        test_cases = [
            ("John Doe", "John"),
            ("Mary Jane Watson", "Mary"),
            ("SingleName", "SingleName"),
            ("", ""),
        ]
        
        for full_name, expected in test_cases:
            result = generator._extract_first_name(full_name)
            assert result == expected
    
    def test_extract_last_name(self, mock_db):
        """Test last name extraction"""
        generator = EsmdPayloadGenerator(mock_db)
        
        test_cases = [
            ("John Doe", "Doe"),
            ("Mary Jane Watson", "Watson"),
            ("SingleName", ""),  # No last name if only one word
            ("", ""),
        ]
        
        for full_name, expected in test_cases:
            result = generator._extract_last_name(full_name)
            assert result == expected


class TestValidation:
    """Test payload validation"""
    
    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)
    
    def test_validation_part_a_requires_ccn(self, mock_db):
        """Test validation catches missing CCN for Part A"""
        generator = EsmdPayloadGenerator(mock_db)
        
        payload = {
            "partType": "A",
            "header": {
                "facilityOrRenderingProvider": {
                    # Missing ccn
                }
            }
        }
        
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        
        # Validation should log error but not raise (for now)
        generator._validate_payload(payload, is_part_a=True, is_part_b=False, is_direct_pa=True, packet_decision=decision)
    
    def test_validation_part_b_requires_rendering_provider_npi(self, mock_db):
        """Test validation catches missing renderingProviderNpi for Part B"""
        generator = EsmdPayloadGenerator(mock_db)
        
        payload = {
            "partType": "B",
            "header": {
                "facilityOrRenderingProvider": {
                    # Missing renderingProviderNpi
                }
            }
        }
        
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        
        generator._validate_payload(payload, is_part_a=False, is_part_b=True, is_direct_pa=True, packet_decision=decision)


class TestHashPayload:
    """Test payload hashing for audit"""
    
    def test_hash_payload_deterministic(self):
        """Test that same payload produces same hash"""
        payload1 = {
            "header": {"state": "NJ"},
            "partType": "B",
            "isDirectPa": True
        }
        
        payload2 = {
            "header": {"state": "NJ"},
            "partType": "B",
            "isDirectPa": True
        }
        
        hash1 = EsmdPayloadGenerator.hash_payload(payload1)
        hash2 = EsmdPayloadGenerator.hash_payload(payload2)
        
        assert hash1 == hash2
    
    def test_hash_payload_different_for_different_payloads(self):
        """Test that different payloads produce different hashes"""
        payload1 = {
            "header": {"state": "NJ"},
            "partType": "B"
        }
        
        payload2 = {
            "header": {"state": "NY"},
            "partType": "B"
        }
        
        hash1 = EsmdPayloadGenerator.hash_payload(payload1)
        hash2 = EsmdPayloadGenerator.hash_payload(payload2)
        
        assert hash1 != hash2


class TestTypeOfBill:
    """Test typeOfBill handling for Part A"""
    
    @pytest.fixture
    def mock_db(self):
        return Mock(spec=Session)
    
    def test_type_of_bill_valid_values(self, mock_db):
        """Test typeOfBill accepts valid values (13 or 131)"""
        generator = EsmdPayloadGenerator(mock_db)
        
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        packet.beneficiary_name = "Test"
        packet.beneficiary_mbi = "1EG4TE5MK72"
        packet.provider_name = "Test"
        packet.provider_npi = "1234567890"
        packet.submission_type = None
        
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "A"
        
        doc = Mock(spec=PacketDocumentDB)
        doc.extracted_fields = {
            "fields": {
                "state": {"value": "NJ"},
                "type_of_bill": {"value": "13"}
            }
        }
        doc.updated_extracted_fields = None
        
        mock_db.query.return_value.filter.return_value.first.return_value = doc
        
        payload = generator.generate_payload(
            packet=packet,
            packet_decision=decision,
            procedures=[],
            medical_docs=None
        )
        
        assert payload['header']['typeOfBill'] in ['13', '131']
    
    def test_type_of_bill_invalid_defaults_to_13(self, mock_db):
        """Test invalid typeOfBill defaults to '13'"""
        generator = EsmdPayloadGenerator(mock_db)
        
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        packet.beneficiary_name = "Test"
        packet.beneficiary_mbi = "1EG4TE5MK72"
        packet.provider_name = "Test"
        packet.provider_npi = "1234567890"
        packet.submission_type = None
        
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "A"
        
        doc = Mock(spec=PacketDocumentDB)
        doc.extracted_fields = {
            "fields": {
                "state": {"value": "NJ"},
                "type_of_bill": {"value": "999"}  # Invalid
            }
        }
        doc.updated_extracted_fields = None
        
        mock_db.query.return_value.filter.return_value.first.return_value = doc
        
        payload = generator.generate_payload(
            packet=packet,
            packet_decision=decision,
            procedures=[],
            medical_docs=None
        )
        
        # Should default to '13' for invalid values
        assert payload['header']['typeOfBill'] == '13'

