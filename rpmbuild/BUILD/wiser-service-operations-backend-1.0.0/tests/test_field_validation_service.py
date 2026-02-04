"""
Unit tests for field_validation_service.py
Tests all validation rules
"""
import pytest
from datetime import datetime
from app.services.field_validation_service import (
    validate_state,
    validate_diagnosis_code_requirement,
    validate_request_type,
    validate_phone_after_fix,
    validate_date_after_fix,
    validate_diagnosis_code_format,
    validate_place_of_service,
    validate_npi,
    validate_provider_address,
    validate_procedure_codes_optional,
    validate_ccn,
    validate_all_fields,
    get_field_value
)


class TestGetFieldValue:
    """Tests for get_field_value() helper"""
    
    def test_get_field_value_found(self):
        """Test getting field value when found"""
        fields = {
            'Requester Phone': {'value': '7328490077'}
        }
        result = get_field_value(fields, ['Requester Phone'])
        assert result == '7328490077'
    
    def test_get_field_value_not_found(self):
        """Test getting field value when not found"""
        fields = {'Other Field': {'value': 'test'}}
        result = get_field_value(fields, ['Requester Phone'])
        assert result is None
    
    def test_get_field_value_empty(self):
        """Test getting field value when empty"""
        fields = {'Requester Phone': {'value': ''}}
        result = get_field_value(fields, ['Requester Phone'])
        assert result is None


class TestValidateState:
    """Tests for validate_state()"""
    
    def test_validate_state_nj(self):
        """Test state is NJ"""
        errors = validate_state("NJ")
        assert len(errors) == 0
    
    def test_validate_state_new_jersey(self):
        """Test state is New Jersey"""
        errors = validate_state("New Jersey")
        assert len(errors) == 0
    
    def test_validate_state_other(self):
        """Test state is not NJ"""
        errors = validate_state("NY")
        assert len(errors) > 0
        assert "must be NJ" in errors[0]
    
    def test_validate_state_empty(self):
        """Test empty state"""
        errors = validate_state("")
        assert len(errors) > 0
        assert "required" in errors[0]


class TestValidateDiagnosisCodeRequirement:
    """Tests for validate_diagnosis_code_requirement()"""
    
    def test_validate_diagnosis_part_a_not_required(self):
        """Test Part A doesn't require diagnosis (unless exception)"""
        errors = validate_diagnosis_code_requirement(
            diagnosis_code=None,
            procedure_codes=['12345'],
            part_type='PART_A'
        )
        assert len(errors) == 0
    
    def test_validate_diagnosis_vagus_required(self):
        """Test Vagus procedure requires diagnosis"""
        errors = validate_diagnosis_code_requirement(
            diagnosis_code=None,
            procedure_codes=['64553'],  # Vagus procedure
            part_type='PART_A'
        )
        assert len(errors) > 0
        assert "required" in errors[0].lower()
    
    def test_validate_diagnosis_missing_for_required(self):
        """Test missing diagnosis for required procedure"""
        errors = validate_diagnosis_code_requirement(
            diagnosis_code="",
            procedure_codes=['64553'],
            part_type='PART_A'
        )
        assert len(errors) > 0
    
    def test_validate_diagnosis_invalid_code(self):
        """Test invalid diagnosis code for procedure"""
        errors = validate_diagnosis_code_requirement(
            diagnosis_code="INVALID",
            procedure_codes=['64553'],
            part_type='PART_A'
        )
        assert len(errors) > 0
    
    def test_validate_diagnosis_n3941_valid(self):
        """Test N3941 is accepted for Vagus Nerve Stimulation (64561)"""
        errors = validate_diagnosis_code_requirement(
            diagnosis_code="N3941",
            procedure_codes=['64561'],  # Vagus Nerve Stimulation
            part_type='PART_A'
        )
        assert len(errors) == 0, f"N3941 should be valid for procedure 64561, got errors: {errors}"
    
    def test_validate_diagnosis_n3941_with_period(self):
        """Test N39.41 (with period) is accepted for Vagus Nerve Stimulation"""
        errors = validate_diagnosis_code_requirement(
            diagnosis_code="N39.41",
            procedure_codes=['64561'],
            part_type='PART_A'
        )
        assert len(errors) == 0, f"N39.41 should be valid for procedure 64561, got errors: {errors}"


class TestValidateRequestType:
    """Tests for validate_request_type()"""
    
    def test_validate_request_type_initial(self):
        """Test request type is Initial"""
        errors = validate_request_type("I")
        assert len(errors) == 0
    
    def test_validate_request_type_resubmission(self):
        """Test request type is Resubmission"""
        errors = validate_request_type("R")
        assert len(errors) == 0
    
    def test_validate_request_type_invalid(self):
        """Test invalid request type"""
        errors = validate_request_type("X")
        assert len(errors) > 0
    
    def test_validate_request_type_empty(self):
        """Test empty request type"""
        errors = validate_request_type("")
        assert len(errors) > 0


class TestValidatePhoneAfterFix:
    """Tests for validate_phone_after_fix()"""
    
    def test_validate_phone_valid(self):
        """Test valid phone (10 digits)"""
        errors = validate_phone_after_fix("7328490077", "Phone")
        assert len(errors) == 0
    
    def test_validate_phone_too_short(self):
        """Test phone too short"""
        errors = validate_phone_after_fix("732849", "Phone")
        assert len(errors) > 0
        assert "10 digits" in errors[0]
    
    def test_validate_phone_too_long(self):
        """Test phone too long"""
        errors = validate_phone_after_fix("17328490077", "Phone")
        assert len(errors) > 0
    
    def test_validate_phone_empty(self):
        """Test empty phone (not required)"""
        errors = validate_phone_after_fix("", "Phone")
        assert len(errors) == 0


class TestValidateDateAfterFix:
    """Tests for validate_date_after_fix()"""
    
    def test_validate_date_valid(self):
        """Test valid date format"""
        errors = validate_date_after_fix("2026-01-28", "Date")
        assert len(errors) == 0
    
    def test_validate_date_invalid_format(self):
        """Test invalid date format"""
        errors = validate_date_after_fix("01/28/2026", "Date")
        assert len(errors) > 0
    
    def test_validate_date_invalid_date(self):
        """Test invalid date values"""
        errors = validate_date_after_fix("2026-13-45", "Date")
        assert len(errors) > 0
    
    def test_validate_date_empty_required(self):
        """Test empty date when required"""
        errors = validate_date_after_fix("", "Date", required=True)
        assert len(errors) > 0


class TestValidateDiagnosisCodeFormat:
    """Tests for validate_diagnosis_code_format()"""
    
    def test_validate_diagnosis_format_valid(self):
        """Test valid diagnosis format (no periods)"""
        errors = validate_diagnosis_code_format("G40011")
        assert len(errors) == 0
    
    def test_validate_diagnosis_format_with_period(self):
        """Test diagnosis with period"""
        errors = validate_diagnosis_code_format("G40.011")
        assert len(errors) > 0
    
    def test_validate_diagnosis_format_multiple(self):
        """Test multiple diagnosis codes"""
        errors = validate_diagnosis_code_format("G40011, M2551")
        assert len(errors) == 0


class TestValidatePlaceOfService:
    """Tests for validate_place_of_service()"""
    
    def test_validate_place_of_service_numeric(self):
        """Test numeric place of service"""
        errors = validate_place_of_service("24", None)
        assert len(errors) == 0
    
    def test_validate_place_of_service_non_numeric(self):
        """Test non-numeric place of service"""
        errors = validate_place_of_service("ABC", None)
        assert len(errors) > 0
    
    def test_validate_place_of_service_both_exist(self):
        """Test both place and location exist (use place)"""
        errors = validate_place_of_service("24", "11")
        assert len(errors) == 0


class TestValidateNPI:
    """Tests for validate_npi()"""
    
    def test_validate_npi_valid(self):
        """Test valid NPI (10 digits)"""
        errors = validate_npi("1234567890", "NPI")
        assert len(errors) == 0
    
    def test_validate_npi_too_short(self):
        """Test NPI too short"""
        errors = validate_npi("123456789", "NPI")
        assert len(errors) > 0
    
    def test_validate_npi_too_long(self):
        """Test NPI too long"""
        errors = validate_npi("12345678901", "NPI")
        assert len(errors) > 0
    
    def test_validate_npi_empty(self):
        """Test empty NPI (not always required)"""
        errors = validate_npi("", "NPI")
        assert len(errors) == 0


class TestValidateProviderAddress:
    """Tests for validate_provider_address()"""
    
    def test_validate_address_state_in_city(self):
        """Test state abbreviation in city as separate word - should error"""
        errors = validate_provider_address(
            address_1="1100 Route 70",
            address_2="",
            city="Whiting NJ",
            state=""
        )
        assert len(errors) > 0
        assert any("NJ" in error for error in errors)
    
    def test_validate_address_city_with_pa_substring(self):
        """Test city name containing PA as substring - should NOT error (Manalapan)"""
        errors = validate_provider_address(
            address_1="50 Franklin Lane",
            address_2="",
            city="Manalapan",
            state="NJ"
        )
        assert len(errors) == 0, f"Manalapan should not trigger error (PA is part of city name), got: {errors}"
    
    def test_validate_address_city_with_ny_substring(self):
        """Test city name containing NY as substring - should NOT error (Parsippany)"""
        errors = validate_provider_address(
            address_1="123 Main St",
            address_2="",
            city="Parsippany",
            state="NJ"
        )
        assert len(errors) == 0, f"Parsippany should not trigger error (NY is part of city name), got: {errors}"
    
    def test_validate_address_city_with_ca_substring(self):
        """Test city name containing CA as substring - should NOT error (Camden, Mullica Hill)"""
        # Test Camden
        errors = validate_provider_address(
            address_1="123 Main St",
            address_2="",
            city="Camden",
            state="NJ"
        )
        assert len(errors) == 0, f"Camden should not trigger error (CA is part of city name), got: {errors}"
        
        # Test Mullica Hill
        errors = validate_provider_address(
            address_1="199 MULLICA HILL RD",
            address_2="",
            city="MULLICA HILL",
            state="NJ"
        )
        assert len(errors) == 0, f"MULLICA HILL should not trigger error (CA is part of city name), got: {errors}"
    
    def test_validate_address_city_with_state_as_separate_word(self):
        """Test city with state abbreviation as separate word - should error"""
        test_cases = [
            ("Manalapan PA", "PA"),
            ("Parsippany NY", "NY"),
            ("Camden CA", "CA"),
            ("Whiting NJ", "NJ"),
            ("Mullica Hill CA", "CA"),
        ]
        
        for city, expected_abbrev in test_cases:
            errors = validate_provider_address(
                address_1="123 Main St",
                address_2="",
                city=city,
                state=""
            )
            assert len(errors) > 0, f"{city} should trigger error (contains {expected_abbrev} as separate word)"
            assert any(expected_abbrev in error for error in errors), \
                f"Error should mention {expected_abbrev}, got: {errors}"
    
    def test_validate_address_suite_in_address1(self):
        """Test suite in address1 when too long"""
        errors = validate_provider_address(
            address_1="1100 Route 70 West Suite 100 This is a very long address that exceeds 50 characters",
            address_2="",
            city="Whiting",
            state="NJ"
        )
        assert len(errors) > 0
    
    def test_validate_address_valid(self):
        """Test valid address"""
        errors = validate_provider_address(
            address_1="1100 Route 70 West",
            address_2="Suite 100",
            city="Whiting",
            state="NJ"
        )
        assert len(errors) == 0


class TestValidateProcedureCodesOptional:
    """Tests for validate_procedure_codes_optional()"""
    
    def test_validate_procedure_codes_both_blank(self):
        """Test both codes blank"""
        errors = validate_procedure_codes_optional(None, None, None, None)
        assert len(errors) == 0
    
    def test_validate_procedure_code_without_units(self):
        """Test procedure code without units"""
        errors = validate_procedure_codes_optional("12345", None, None, None)
        assert len(errors) > 0
    
    def test_validate_procedure_code_with_units(self):
        """Test procedure code with units"""
        errors = validate_procedure_codes_optional("12345", None, "5", None)
        assert len(errors) == 0


class TestValidateCCN:
    """Tests for validate_ccn()"""
    
    def test_validate_ccn_part_a_starts_31(self):
        """Test Part A CCN starts with 31"""
        errors = validate_ccn("31123456", "PART_A")
        assert len(errors) == 0
    
    def test_validate_ccn_part_a_starts_83(self):
        """Test Part A CCN starts with 83"""
        errors = validate_ccn("83123456", "PART_A")
        assert len(errors) == 0
    
    def test_validate_ccn_part_a_invalid_prefix(self):
        """Test Part A CCN invalid prefix"""
        errors = validate_ccn("21123456", "PART_A")
        assert len(errors) > 0
    
    def test_validate_ccn_part_a_non_digits(self):
        """Test Part A CCN non-digits"""
        errors = validate_ccn("31ABC456", "PART_A")
        assert len(errors) > 0
    
    def test_validate_ccn_part_b(self):
        """Test Part B (no validation)"""
        errors = validate_ccn("123456", "PART_B")
        assert len(errors) == 0


class TestValidateAllFields:
    """Tests for validate_all_fields()"""
    
    def test_validate_all_fields_no_errors(self):
        """Test all fields valid"""
        extracted_fields = {
            'fields': {
                'Rendering/Facility State': {'value': 'NJ'},
                'Request Type': {'value': 'I'},
                'Requester Phone': {'value': '7328490077'},
                'Anticipated Date of Service': {'value': '2026-01-28'}
            }
        }
        
        class MockPacket:
            pass
        
        mock_packet = MockPacket()
        result = validate_all_fields(extracted_fields, mock_packet, None)
        assert result['has_errors'] is False
        assert len(result['field_errors']) == 0
    
    def test_validate_all_fields_multiple_errors(self):
        """Test multiple validation errors"""
        extracted_fields = {
            'fields': {
                'Rendering/Facility State': {'value': 'NY'},
                'Request Type': {'value': 'X'},
                'Requester Phone': {'value': '732849'}
            }
        }
        
        class MockPacket:
            pass
        
        mock_packet = MockPacket()
        result = validate_all_fields(extracted_fields, mock_packet, None)
        assert result['has_errors'] is True
        assert len(result['field_errors']) > 0
    
    def test_validate_all_fields_empty(self):
        """Test empty extracted_fields"""
        result = validate_all_fields({}, None, None)
        assert result['has_errors'] is False
    
    def test_validate_all_fields_none(self):
        """Test None extracted_fields"""
        result = validate_all_fields(None, None, None)
        assert result['has_errors'] is False
