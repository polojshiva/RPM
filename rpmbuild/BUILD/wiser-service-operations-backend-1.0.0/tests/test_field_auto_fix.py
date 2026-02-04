"""
Unit tests for field_auto_fix.py service
Tests all auto-fix normalization functions
"""
import pytest
from app.services.field_auto_fix import (
    normalize_phone_number,
    normalize_fax_number,
    normalize_date,
    normalize_diagnosis_code,
    normalize_address,
    apply_auto_fix_to_fields
)


class TestNormalizePhoneNumber:
    """Tests for normalize_phone_number()"""
    
    def test_normalize_phone_with_special_chars(self):
        """Test phone with special characters"""
        result, is_valid = normalize_phone_number("(732) 849-0077")
        assert result == "7328490077"
        assert is_valid is True
    
    def test_normalize_phone_with_dashes(self):
        """Test phone with dashes"""
        result, is_valid = normalize_fax_number("732-849-0077")
        assert result == "7328490077"
        assert is_valid is True
    
    def test_normalize_phone_too_short(self):
        """Test phone that's too short"""
        result, is_valid = normalize_phone_number("732849")
        assert result == "732849"
        assert is_valid is False
    
    def test_normalize_phone_too_long(self):
        """Test phone that's too long"""
        result, is_valid = normalize_phone_number("17328490077")
        assert result == "17328490077"
        assert is_valid is False
    
    def test_normalize_phone_empty(self):
        """Test empty phone"""
        result, is_valid = normalize_phone_number("")
        assert result == ""
        assert is_valid is False
    
    def test_normalize_phone_with_spaces(self):
        """Test phone with spaces"""
        result, is_valid = normalize_phone_number("732 849 0077")
        assert result == "7328490077"
        assert is_valid is True


class TestNormalizeFaxNumber:
    """Tests for normalize_fax_number()"""
    
    def test_normalize_fax_with_special_chars(self):
        """Test fax with special characters"""
        result, is_valid = normalize_fax_number("(732) 849-0015")
        assert result == "7328490015"
        assert is_valid is True
    
    def test_normalize_fax_with_dashes(self):
        """Test fax with dashes"""
        result, is_valid = normalize_fax_number("732-849-0015")
        assert result == "7328490015"
        assert is_valid is True
    
    def test_normalize_fax_too_short(self):
        """Test fax that's too short"""
        result, is_valid = normalize_fax_number("732849")
        assert result == "732849"
        assert is_valid is False
    
    def test_normalize_fax_empty(self):
        """Test empty fax"""
        result, is_valid = normalize_fax_number("")
        assert result == ""
        assert is_valid is False


class TestNormalizeDate:
    """Tests for normalize_date()"""
    
    def test_normalize_date_yyyy_mm_dd(self):
        """Test date already in YYYY-MM-DD format"""
        result, is_valid = normalize_date("2026-01-28")
        assert result == "2026-01-28"
        assert is_valid is True
    
    def test_normalize_date_mm_dd_yyyy(self):
        """Test date in MM/DD/YYYY format"""
        result, is_valid = normalize_date("01/28/2026")
        assert result == "2026-01-28"
        assert is_valid is True
    
    def test_normalize_date_dd_mm_yyyy(self):
        """Test date in DD/MM/YYYY format (day > 12)"""
        result, is_valid = normalize_date("28/01/2026")
        assert result == "2026-01-28"
        assert is_valid is True
    
    def test_normalize_date_yyyy_mm_dd_slash(self):
        """Test date in YYYY/MM/DD format"""
        result, is_valid = normalize_date("2026/01/28")
        assert result == "2026-01-28"
        assert is_valid is True
    
    def test_normalize_date_invalid_format(self):
        """Test date with invalid format"""
        result, is_valid = normalize_date("Jan 28, 2026")
        assert result == ""
        assert is_valid is False
    
    def test_normalize_date_invalid_date(self):
        """Test date with invalid date values"""
        result, is_valid = normalize_date("2026-13-45")
        assert result == ""
        assert is_valid is False
    
    def test_normalize_date_empty(self):
        """Test empty date"""
        result, is_valid = normalize_date("")
        assert result == ""
        assert is_valid is False


class TestNormalizeDiagnosisCode:
    """Tests for normalize_diagnosis_code()"""
    
    def test_normalize_diagnosis_single_with_period(self):
        """Test single diagnosis code with period"""
        result, is_valid = normalize_diagnosis_code("G40.011")
        assert result == "G40011"
        assert is_valid is True
    
    def test_normalize_diagnosis_multiple(self):
        """Test multiple diagnosis codes"""
        result, is_valid = normalize_diagnosis_code("G40.011, M2551")
        assert result == "G40011, M2551"
        assert is_valid is True
    
    def test_normalize_diagnosis_trailing_period(self):
        """Test diagnosis code with trailing period"""
        result, is_valid = normalize_diagnosis_code("812.")
        assert result == "812"
        assert is_valid is True
    
    def test_normalize_diagnosis_empty(self):
        """Test empty diagnosis code"""
        result, is_valid = normalize_diagnosis_code("")
        assert result == ""
        assert is_valid is False
    
    def test_normalize_diagnosis_multiple_periods(self):
        """Test diagnosis code with multiple periods"""
        result, is_valid = normalize_diagnosis_code("G40.011.123")
        assert result == "G40011123"
        assert is_valid is True


class TestNormalizeAddress:
    """Tests for normalize_address()"""
    
    def test_normalize_address_state_in_city(self):
        """Test moving state from city to state field when state is separate word"""
        result = normalize_address(city="Whiting NJ", state="")
        assert result['city'][0] == "Whiting"
        assert result['state'][0] == "NJ"
        assert result['city'][1] is True
        assert result['state'][1] is True
    
    def test_normalize_address_city_with_pa_substring(self):
        """Test city name containing PA as substring - should NOT extract (Manalapan)"""
        result = normalize_address(city="Manalapan", state="")
        # Should NOT extract PA from Manalapan - PA is part of the city name
        assert result['city'][0] == "Manalapan", f"City should remain 'Manalapan', got: {result['city'][0]}"
        assert result['state'][0] == "", f"State should remain empty, got: {result['state'][0]}"
    
    def test_normalize_address_city_with_ny_substring(self):
        """Test city name containing NY as substring - should NOT extract (Parsippany)"""
        result = normalize_address(city="Parsippany", state="")
        # Should NOT extract NY from Parsippany - NY is part of the city name
        assert result['city'][0] == "Parsippany", f"City should remain 'Parsippany', got: {result['city'][0]}"
        assert result['state'][0] == "", f"State should remain empty, got: {result['state'][0]}"
    
    def test_normalize_address_city_with_ca_substring(self):
        """Test city name containing CA as substring - should NOT extract (Camden, Mullica Hill)"""
        # Test Camden
        result = normalize_address(city="Camden", state="")
        assert result['city'][0] == "Camden", f"City should remain 'Camden', got: {result['city'][0]}"
        assert result['state'][0] == "", f"State should remain empty, got: {result['state'][0]}"
        
        # Test Mullica Hill
        result = normalize_address(city="MULLICA HILL", state="")
        assert result['city'][0] == "MULLICA HILL", f"City should remain 'MULLICA HILL', got: {result['city'][0]}"
        assert result['state'][0] == "", f"State should remain empty, got: {result['state'][0]}"
    
    def test_normalize_address_city_with_state_as_separate_word(self):
        """Test city with state abbreviation as separate word - should extract"""
        test_cases = [
            ("Manalapan PA", "Manalapan", "PA"),
            ("Parsippany NY", "Parsippany", "NY"),
            ("Camden CA", "Camden", "CA"),
            ("Mullica Hill CA", "Mullica Hill", "CA"),
        ]
        
        for city_input, expected_city, expected_state in test_cases:
            result = normalize_address(city=city_input, state="")
            assert result['city'][0] == expected_city, \
                f"For '{city_input}', city should be '{expected_city}', got: {result['city'][0]}"
            assert result['state'][0] == expected_state, \
                f"For '{city_input}', state should be '{expected_state}', got: {result['state'][0]}"
    
    def test_normalize_address_new_jersey(self):
        """Test normalizing New Jersey to NJ"""
        result = normalize_address(state="New Jersey")
        assert result['state'][0] == "NJ"
        assert result['state'][1] is True
    
    def test_normalize_address_suite_to_address2(self):
        """Test moving suite from address1 to address2"""
        result = normalize_address(
            address_1="1100 Route 70 West Suite 100",
            address_2=""
        )
        # Should extract suite to address2
        assert "Suite" in result['address_2'][0] or "suite" in result['address_2'][0].lower()
        assert result['address_1'][1] is True
    
    def test_normalize_address_no_changes(self):
        """Test address that needs no changes"""
        result = normalize_address(
            address_1="1100 Route 70 West",
            city="Whiting",
            state="NJ",
            zip_code="08759"
        )
        assert result['address_1'][0] == "1100 Route 70 West"
        assert result['city'][0] == "Whiting"
        assert result['state'][0] == "NJ"
        assert result['zip'][0] == "08759"
    
    def test_normalize_address_empty(self):
        """Test empty address fields"""
        result = normalize_address()
        assert result['address_1'][0] == ""
        assert result['address_2'][0] == ""
        assert result['city'][0] == ""
        assert result['state'][0] == ""
        assert result['zip'][0] == ""


class TestApplyAutoFixToFields:
    """Tests for apply_auto_fix_to_fields()"""
    
    def test_apply_auto_fix_phone(self):
        """Test auto-fixing phone number"""
        extracted_fields = {
            'fields': {
                'Requester Phone': {
                    'value': '(732) 849-0077',
                    'confidence': 0.95,
                    'field_type': 'STRING'
                }
            }
        }
        updated, results = apply_auto_fix_to_fields(extracted_fields)
        assert updated['fields']['Requester Phone']['value'] == '7328490077'
        assert 'Requester Phone' in results
        assert results['Requester Phone']['status'] == 'success'
    
    def test_apply_auto_fix_date(self):
        """Test auto-fixing date"""
        extracted_fields = {
            'fields': {
                'Anticipated Date of Service': {
                    'value': '01/28/2026',
                    'confidence': 0.90,
                    'field_type': 'STRING'
                }
            }
        }
        updated, results = apply_auto_fix_to_fields(extracted_fields)
        assert updated['fields']['Anticipated Date of Service']['value'] == '2026-01-28'
        assert 'Anticipated Date of Service' in results
    
    def test_apply_auto_fix_diagnosis(self):
        """Test auto-fixing diagnosis code"""
        extracted_fields = {
            'fields': {
                'Diagnosis Codes': {
                    'value': 'G40.011, M2551',
                    'confidence': 0.85,
                    'field_type': 'STRING'
                }
            }
        }
        updated, results = apply_auto_fix_to_fields(extracted_fields)
        assert updated['fields']['Diagnosis Codes']['value'] == 'G40011, M2551'
        assert 'Diagnosis Codes' in results
    
    def test_apply_auto_fix_address(self):
        """Test auto-fixing address"""
        extracted_fields = {
            'fields': {
                'Rendering/Facility City': {
                    'value': 'Whiting NJ',
                    'confidence': 0.95,
                    'field_type': 'STRING'
                },
                'Rendering/Facility State': {
                    'value': '',
                    'confidence': 0.0,
                    'field_type': 'STRING'
                }
            }
        }
        updated, results = apply_auto_fix_to_fields(extracted_fields)
        # State should be extracted from city
        assert 'Rendering/Facility City' in results or 'Rendering/Facility State' in results
    
    def test_apply_auto_fix_multiple_fields(self):
        """Test auto-fixing multiple fields at once"""
        extracted_fields = {
            'fields': {
                'Requester Phone': {'value': '(732) 849-0077'},
                'Requester Fax': {'value': '732-849-0015'},
                'Anticipated Date of Service': {'value': '01/28/2026'}
            }
        }
        updated, results = apply_auto_fix_to_fields(extracted_fields)
        assert len(results) >= 3
        assert updated['fields']['Requester Phone']['value'] == '7328490077'
        assert updated['fields']['Requester Fax']['value'] == '7328490015'
        assert updated['fields']['Anticipated Date of Service']['value'] == '2026-01-28'
    
    def test_apply_auto_fix_preserves_other_fields(self):
        """Test that non-fixable fields are preserved"""
        extracted_fields = {
            'fields': {
                'Requester Phone': {'value': '(732) 849-0077'},
                'Provider Name': {'value': 'Garden State Medical Center'},
                'Beneficiary Name': {'value': 'John Doe'}
            }
        }
        updated, results = apply_auto_fix_to_fields(extracted_fields)
        # Phone should be fixed
        assert 'Requester Phone' in results
        # Other fields should be preserved
        assert updated['fields']['Provider Name']['value'] == 'Garden State Medical Center'
        assert updated['fields']['Beneficiary Name']['value'] == 'John Doe'
    
    def test_apply_auto_fix_empty_fields(self):
        """Test with empty extracted_fields"""
        extracted_fields = {'fields': {}}
        updated, results = apply_auto_fix_to_fields(extracted_fields)
        assert updated == extracted_fields
        assert results == {}
    
    def test_apply_auto_fix_none_fields(self):
        """Test with None extracted_fields"""
        updated, results = apply_auto_fix_to_fields(None)
        assert updated is None
        assert results == {}
