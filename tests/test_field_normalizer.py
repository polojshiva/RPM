"""
Unit tests for FieldNormalizer utility
"""
import pytest
from app.utils.field_normalizer import FieldNormalizer


class TestFieldNormalizer:
    """Test field normalization functionality"""
    
    def test_normalize_field_name_title_case(self):
        """Test field name normalization to Title Case"""
        assert FieldNormalizer.normalize_field_name("beneficiary name") == "Beneficiary Name"
        assert FieldNormalizer.normalize_field_name("Provider NPI") == "Facility Provider NPI"  # Mapped via FIELD_NAME_MAPPING
        assert FieldNormalizer.normalize_field_name("procedure code set 1") == "Procedure Code set 1"
        assert FieldNormalizer.normalize_field_name("BENEFICIARY_MBI") == "Beneficiary_mbi"  # Title case conversion (underscores preserved)
    
    def test_normalize_field_name_mapping(self):
        """Test field name mapping for known variations"""
        assert FieldNormalizer.normalize_field_name("mbi") == "Beneficiary Medicare ID"
        assert FieldNormalizer.normalize_field_name("provider npi") == "Facility Provider NPI"
        assert FieldNormalizer.normalize_field_name("procedure code 1") == "Procedure Code set 1"
    
    def test_normalize_field_value_dict(self):
        """Test field value normalization from dict"""
        field_data = {
            'value': '  Test Value  ',
            'confidence': 1,  # int
            'field_type': 'DocumentFieldType.STRING',
            'source': 'OCR'
        }
        normalized = FieldNormalizer.normalize_field_value(field_data)
        
        assert normalized['value'] == 'Test Value'
        assert normalized['confidence'] == 1.0  # float
        assert normalized['field_type'] == 'STRING'  # prefix removed
        assert normalized['source'] == 'OCR'
    
    def test_normalize_field_value_simple(self):
        """Test field value normalization from simple value"""
        normalized = FieldNormalizer.normalize_field_value("Simple Value")
        
        assert normalized['value'] == 'Simple Value'
        assert normalized['confidence'] == 1.0
        assert normalized['field_type'] == 'STRING'
        assert normalized['source'] == 'OCR'
    
    def test_deduplicate_fields_no_duplicates(self):
        """Test deduplication with no duplicates"""
        fields = {
            'Beneficiary Name': {'value': 'John Doe'},
            'Facility Provider NPI': {'value': '1234567890'}  # Use normalized name
        }
        deduplicated = FieldNormalizer.deduplicate_fields(fields)
        
        assert len(deduplicated) == 2
        assert 'Beneficiary Name' in deduplicated
        assert 'Facility Provider NPI' in deduplicated
    
    def test_deduplicate_fields_case_duplicates(self):
        """Test deduplication with case-insensitive duplicates"""
        fields = {
            'Beneficiary Name': {'value': 'John Doe', 'confidence': 0.9},
            'beneficiary name': {'value': 'Jane Doe', 'confidence': 0.95}  # Higher confidence
        }
        deduplicated = FieldNormalizer.deduplicate_fields(fields)
        
        # Should keep the one with higher confidence
        assert len(deduplicated) == 1
        assert 'Beneficiary Name' in deduplicated
        assert deduplicated['Beneficiary Name']['value'] == 'Jane Doe'
    
    def test_clean_raw_structure_removes_fields(self):
        """Test raw structure cleaning removes duplicate fields"""
        raw_data = {
            'source': 'payload',
            'ocr': {
                'fields': {'Field1': 'value1'},  # Should be removed
                'doc_type': 'coversheet-extraction',
                'model_id': 'model1'
            }
        }
        cleaned = FieldNormalizer.clean_raw_structure(raw_data, 'payload')
        
        assert 'fields' not in cleaned
        assert 'ocr' in cleaned
        assert 'fields' not in cleaned['ocr']  # Should be removed
        assert cleaned['ocr']['doc_type'] == 'coversheet-extraction'
        assert cleaned['ocr']['model_id'] == 'model1'
    
    def test_normalize_extracted_fields_full(self):
        """Test full normalization of extracted_fields"""
        extracted_fields = {
            'fields': {
                'Beneficiary Name': {'value': 'John Doe', 'confidence': 1, 'field_type': 'DocumentFieldType.STRING'},
                'beneficiary name': {'value': 'Jane Doe', 'confidence': 0.9}  # Duplicate
            },
            'raw': {
                'source': 'payload',
                'ocr': {
                    'fields': {'Field1': 'value1'},  # Should be removed
                    'doc_type': 'coversheet-extraction'
                }
            },
            'source': 'PAYLOAD_INITIAL'
        }
        
        normalized = FieldNormalizer.normalize_extracted_fields(extracted_fields, 'PAYLOAD_INITIAL')
        
        # Check fields are deduplicated and normalized
        assert len(normalized['fields']) == 1
        assert 'Beneficiary Name' in normalized['fields']
        
        # Check raw structure is cleaned
        assert 'fields' not in normalized['raw']
        assert 'fields' not in normalized['raw'].get('ocr', {})
        
        # Check field values are normalized
        field_data = normalized['fields']['Beneficiary Name']
        assert field_data['confidence'] == 1.0  # float
        assert field_data['field_type'] == 'STRING'  # prefix removed


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

