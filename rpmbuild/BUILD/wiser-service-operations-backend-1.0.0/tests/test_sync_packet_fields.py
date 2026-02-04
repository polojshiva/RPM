"""
Unit tests for sync_packet_from_extracted_fields function
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock
from app.utils.packet_sync import sync_packet_from_extracted_fields
from app.models.packet_db import PacketDB


class TestSyncPacketFromExtractedFields:
    """Test packet table field synchronization"""
    
    def test_sync_hcpcs_from_procedure_codes(self):
        """Test HCPCS is populated from Procedure Code set 1/2/3"""
        packet = Mock(spec=PacketDB)
        packet.hcpcs = None
        packet.procedure_code_1 = None
        packet.procedure_code_2 = None
        packet.procedure_code_3 = None
        packet.updated_at = None
        
        extracted_fields = {
            'fields': {
                'Procedure Code set 1': {'value': '64483'},
                'Procedure Code set 2': {'value': '64484'},
                'Procedure Code set 3': {'value': '64485'}
            }
        }
        
        result = sync_packet_from_extracted_fields(
            packet=packet,
            extracted_fields_dict=extracted_fields,
            now=datetime.now(timezone.utc),
            db=Mock()
        )
        
        assert result is True
        assert packet.hcpcs == '64483, 64484, 64485'
        assert packet.procedure_code_1 == '64483'
        assert packet.procedure_code_2 == '64484'
        assert packet.procedure_code_3 == '64485'
    
    def test_sync_hcpcs_single_code(self):
        """Test HCPCS with only one procedure code"""
        packet = Mock(spec=PacketDB)
        packet.hcpcs = None
        packet.procedure_code_1 = None
        packet.procedure_code_2 = None
        packet.procedure_code_3 = None
        packet.updated_at = None
        
        extracted_fields = {
            'fields': {
                'Procedure Code set 1': {'value': '64483'}
            }
        }
        
        result = sync_packet_from_extracted_fields(
            packet=packet,
            extracted_fields_dict=extracted_fields,
            now=datetime.now(timezone.utc),
            db=Mock()
        )
        
        assert result is True
        assert packet.hcpcs == '64483'
        assert packet.procedure_code_1 == '64483'
    
    def test_sync_submission_type_expedited(self):
        """Test submission_type normalization for expedited"""
        packet = Mock(spec=PacketDB)
        packet.submission_type = None
        packet.updated_at = None
        
        extracted_fields = {
            'fields': {
                'Submission Type': {'value': 'expedited-initial'}
            }
        }
        
        result = sync_packet_from_extracted_fields(
            packet=packet,
            extracted_fields_dict=extracted_fields,
            now=datetime.now(timezone.utc),
            db=Mock()
        )
        
        assert result is True
        assert packet.submission_type == 'Expedited'
    
    def test_sync_submission_type_standard(self):
        """Test submission_type normalization for standard"""
        packet = Mock(spec=PacketDB)
        packet.submission_type = None
        packet.updated_at = None
        
        extracted_fields = {
            'fields': {
                'Submission Type': {'value': 'standard-initial'}
            }
        }
        
        result = sync_packet_from_extracted_fields(
            packet=packet,
            extracted_fields_dict=extracted_fields,
            now=datetime.now(timezone.utc),
            db=Mock()
        )
        
        assert result is True
        assert packet.submission_type == 'Standard'
    
    def test_sync_provider_fax(self):
        """Test provider_fax normalization"""
        packet = Mock(spec=PacketDB)
        packet.provider_fax = None
        packet.updated_at = None
        
        extracted_fields = {
            'fields': {
                'Requester Fax': {'value': '(908) 684-3301'}
            }
        }
        
        result = sync_packet_from_extracted_fields(
            packet=packet,
            extracted_fields_dict=extracted_fields,
            now=datetime.now(timezone.utc),
            db=Mock()
        )
        
        assert result is True
        assert packet.provider_fax == '9086843301'  # Digits only
    
    def test_sync_all_fields_together(self):
        """Test syncing all new fields together"""
        packet = Mock(spec=PacketDB)
        packet.hcpcs = None
        packet.procedure_code_1 = None
        packet.procedure_code_2 = None
        packet.procedure_code_3 = None
        packet.submission_type = None
        packet.provider_fax = None
        packet.beneficiary_name = "TBD"
        packet.beneficiary_mbi = "TBD"
        packet.provider_name = "TBD"
        packet.provider_npi = "TBD"
        packet.updated_at = None
        
        extracted_fields = {
            'fields': {
                'Beneficiary First Name': {'value': 'John'},
                'Beneficiary Last Name': {'value': 'Doe'},
                'Beneficiary Medicare ID': {'value': '6WM3CK2WX96'},
                'Facility Provider Name': {'value': 'Test Provider'},
                'Facility Provider NPI': {'value': '1619025038'},
                'Requester Fax': {'value': '9086843301'},
                'Procedure Code set 1': {'value': '64483'},
                'Procedure Code set 2': {'value': '64484'},
                'Submission Type': {'value': 'expedited-initial'}
            }
        }
        
        result = sync_packet_from_extracted_fields(
            packet=packet,
            extracted_fields_dict=extracted_fields,
            now=datetime.now(timezone.utc),
            db=Mock()
        )
        
        assert result is True
        assert packet.beneficiary_name == 'John Doe'
        assert packet.beneficiary_mbi == '6WM3CK2WX96'
        assert packet.provider_name == 'Test Provider'
        assert packet.provider_npi == '1619025038'
        assert packet.provider_fax == '9086843301'
        assert packet.hcpcs == '64483, 64484'
        assert packet.procedure_code_1 == '64483'
        assert packet.procedure_code_2 == '64484'
        assert packet.submission_type == 'Expedited'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

