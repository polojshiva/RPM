#!/usr/bin/env python3
"""Comprehensive check of packet data after field updates"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_validation_db import PacketValidationDB
import json

def check_packet_complete(external_id: str):
    db = SessionLocal()
    try:
        packet = db.query(PacketDB).filter(PacketDB.external_id == external_id).first()
        if not packet:
            print(f"❌ Packet {external_id} not found")
            return
        
        print(f"✅ Packet found: {external_id}")
        print(f"   packet_id: {packet.packet_id}")
        print(f"   has_field_validation_errors: {packet.has_field_validation_errors}")
        
        # Get document
        document = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not document:
            print("❌ No document found")
            return
        
        print(f"\n=== DOCUMENT EXTRACTED FIELDS ===")
        print(f"Document ID: {document.external_id}")
        
        # Check updated_extracted_fields (working copy)
        if document.updated_extracted_fields:
            fields = document.updated_extracted_fields.get('fields', {})
            print(f"\n📝 Updated Extracted Fields (Working Copy):")
            print(f"   Total fields: {len(fields)}")
            
            # Check specific fields that were likely corrected
            state_fields = ['Rendering/Facility State', 'Facility Provider State', 'State']
            npi_fields = ['Facility Provider NPI', 'Rendering/Facility NPI', 'Facility Provider N P I']
            
            print(f"\n   State field values:")
            for field_name in state_fields:
                if field_name in fields:
                    field_data = fields[field_name]
                    value = field_data.get('value', '') if isinstance(field_data, dict) else field_data
                    print(f"     {field_name}: '{value}'")
            
            print(f"\n   Facility NPI field values:")
            for field_name in npi_fields:
                if field_name in fields:
                    field_data = fields[field_name]
                    value = field_data.get('value', '') if isinstance(field_data, dict) else field_data
                    print(f"     {field_name}: '{value}'")
        else:
            print("❌ No updated_extracted_fields found")
        
        # Check extracted_fields (baseline)
        if document.extracted_fields:
            fields = document.extracted_fields.get('fields', {})
            print(f"\n📄 Extracted Fields (Baseline):")
            print(f"   Total fields: {len(fields)}")
        else:
            print("❌ No extracted_fields found")
        
        # Check update history
        if document.extracted_fields_update_history:
            print(f"\n📚 Update History:")
            print(f"   Total entries: {len(document.extracted_fields_update_history)}")
            latest = document.extracted_fields_update_history[-1] if document.extracted_fields_update_history else None
            if latest:
                print(f"   Latest update:")
                print(f"     Type: {latest.get('type', 'N/A')}")
                print(f"     Updated at: {latest.get('updated_at', 'N/A')}")
                print(f"     Updated by: {latest.get('updated_by', 'N/A')}")
                changed = latest.get('changed_fields', {})
                if changed:
                    print(f"     Changed fields: {len(changed)}")
                    for field, change in list(changed.items())[:5]:
                        print(f"       {field}: '{change.get('old', '')}' → '{change.get('new', '')}'")
        
        # Check packet table columns (synced values)
        print(f"\n=== PACKET TABLE COLUMNS (Synced) ===")
        print(f"   beneficiary_name: {getattr(packet, 'beneficiary_name', 'N/A')}")
        print(f"   beneficiary_mbi: {getattr(packet, 'beneficiary_mbi', 'N/A')}")
        print(f"   provider_name: {getattr(packet, 'provider_name', 'N/A')}")
        print(f"   provider_npi: {getattr(packet, 'provider_npi', 'N/A')}")
        print(f"   submission_type: {getattr(packet, 'submission_type', 'N/A')}")
        # Check if state column exists
        if hasattr(packet, 'state'):
            print(f"   state: {packet.state}")
        elif hasattr(packet, 'provider_state'):
            print(f"   provider_state: {packet.provider_state}")
        elif hasattr(packet, 'facility_state'):
            print(f"   facility_state: {packet.facility_state}")
        
        # Check validation records
        print(f"\n=== VALIDATION RECORDS ===")
        validations = db.query(PacketValidationDB).filter(
            PacketValidationDB.packet_id == packet.packet_id,
            PacketValidationDB.validation_type == 'FIELD_VALIDATION'
        ).order_by(PacketValidationDB.created_at.desc()).all()
        
        print(f"   Total FIELD_VALIDATION records: {len(validations)}")
        if validations:
            latest = validations[0]
            print(f"   Latest validation:")
            print(f"     Status: {latest.validation_status}")
            print(f"     Is Passed: {latest.is_passed}")
            print(f"     Validated at: {latest.validated_at}")
            if latest.validation_result:
                field_errors = latest.validation_result.get('field_errors', {})
                print(f"     Field errors: {len(field_errors)}")
                if field_errors:
                    for field, errors in field_errors.items():
                        print(f"       {field}: {errors}")
                else:
                    print(f"       ✅ No field errors!")
        
        print(f"\n=== SUMMARY ===")
        print(f"✅ Validation flag: {'PASSED' if not packet.has_field_validation_errors else 'FAILED'}")
        print(f"✅ Latest validation: {'PASSED' if validations and validations[0].is_passed else 'FAILED' if validations else 'N/A'}")
        print(f"✅ Fields updated: {'YES' if document.updated_extracted_fields else 'NO'}")
        print(f"✅ History logged: {'YES' if document.extracted_fields_update_history else 'NO'}")
        
    finally:
        db.close()

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    check_packet_complete('TEST-ERRORS-1769633369')
