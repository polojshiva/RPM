#!/usr/bin/env python3
"""
Re-validate existing packets that have N3941 diagnosis code.
This will clear old validation errors and re-run validation with the updated code.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_validation_db import PacketValidationDB
from app.services.field_validation_service import validate_all_fields
from app.services.validation_persistence import save_field_validation_errors, update_packet_validation_flag
from sqlalchemy import and_, or_
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_packets_with_n3941(db):
    """Find all packets that have N3941 in their diagnosis codes"""
    packets_to_revalidate = []
    
    # Get all documents with extracted fields
    documents = db.query(PacketDocumentDB).filter(
        or_(
            PacketDocumentDB.extracted_fields.isnot(None),
            PacketDocumentDB.updated_extracted_fields.isnot(None)
        )
    ).all()
    
    print(f"Checking {len(documents)} documents for N3941 diagnosis code...")
    
    for doc in documents:
        # Check both extracted_fields and updated_extracted_fields
        fields_to_check = []
        if doc.extracted_fields:
            fields_to_check.append(doc.extracted_fields)
        if doc.updated_extracted_fields:
            fields_to_check.append(doc.updated_extracted_fields)
        
        for fields_dict in fields_to_check:
            fields = fields_dict.get('fields', {}) if isinstance(fields_dict, dict) else {}
            
            # Check diagnosis code fields
            diagnosis_field_names = ['Diagnosis Codes', 'Diagnosis Code', 'Diagnosis codes', 'diagnosis_code']
            for field_name in diagnosis_field_names:
                if field_name in fields:
                    field_data = fields[field_name]
                    if isinstance(field_data, dict):
                        diagnosis_code = field_data.get('value', '')
                    else:
                        diagnosis_code = str(field_data)
                    
                    # Check if N3941 is in the diagnosis code (case-insensitive, handle periods)
                    if diagnosis_code:
                        diagnosis_clean = diagnosis_code.upper().replace('.', '').replace(' ', '')
                        if 'N3941' in diagnosis_clean:
                            # Get the packet
                            packet = db.query(PacketDB).filter(PacketDB.packet_id == doc.packet_id).first()
                            if packet:
                                packets_to_revalidate.append((packet, doc, fields_dict))
                                print(f"  Found: {packet.external_id} - Diagnosis: {diagnosis_code}")
                            break
    
    return packets_to_revalidate


def revalidate_packet(packet, document, fields_dict, db):
    """Re-validate a single packet"""
    try:
        # Run validation with updated code
        validation_result = validate_all_fields(
            extracted_fields=fields_dict,
            packet=packet,
            db_session=db
        )
        
        # Save new validation results (this will deactivate old ones)
        save_field_validation_errors(
            packet_id=packet.packet_id,
            validation_result=validation_result,
            db_session=db
        )
        
        # Update packet flag
        update_packet_validation_flag(
            packet_id=packet.packet_id,
            has_errors=validation_result['has_errors'],
            db_session=db
        )
        
        return validation_result
        
    except Exception as e:
        logger.error(f"Error re-validating packet {packet.external_id}: {e}")
        return None


def revalidate_all_packets_with_n3941():
    """Re-validate all packets that have N3941 diagnosis code"""
    db = SessionLocal()
    try:
        print("=" * 80)
        print("Re-validating packets with N3941 diagnosis code")
        print("=" * 80)
        
        # Find all packets with N3941
        packets_to_revalidate = find_packets_with_n3941(db)
        
        if not packets_to_revalidate:
            print("\n[INFO] No packets found with N3941 diagnosis code")
            return
        
        print(f"\nFound {len(packets_to_revalidate)} packet(s) to re-validate")
        
        # Re-validate each packet
        fixed_count = 0
        still_has_errors_count = 0
        
        for packet, document, fields_dict in packets_to_revalidate:
            print(f"\nRe-validating: {packet.external_id}")
            
            # Get current validation status
            old_has_errors = packet.has_field_validation_errors
            
            # Re-validate
            validation_result = revalidate_packet(packet, document, fields_dict, db)
            
            if validation_result:
                db.commit()
                db.refresh(packet)
                
                new_has_errors = packet.has_field_validation_errors
                
                if old_has_errors and not new_has_errors:
                    print(f"  [FIXED] Validation errors cleared!")
                    fixed_count += 1
                elif new_has_errors:
                    print(f"  [WARN] Still has validation errors:")
                    for field, errors in validation_result.get('field_errors', {}).items():
                        print(f"    - {field}: {', '.join(errors)}")
                    still_has_errors_count += 1
                else:
                    print(f"  [OK] No validation errors (was already correct)")
            else:
                print(f"  [ERROR] Failed to re-validate")
        
        print("\n" + "=" * 80)
        print("Re-validation complete!")
        print("=" * 80)
        print(f"Total packets processed: {len(packets_to_revalidate)}")
        print(f"Fixed (errors cleared): {fixed_count}")
        print(f"Still has errors: {still_has_errors_count}")
        print(f"No errors (already correct): {len(packets_to_revalidate) - fixed_count - still_has_errors_count}")
        
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


def revalidate_specific_packet(packet_external_id: str):
    """Re-validate a specific packet by external_id"""
    db = SessionLocal()
    try:
        packet = db.query(PacketDB).filter(PacketDB.external_id == packet_external_id).first()
        
        if not packet:
            print(f"[ERROR] Packet not found: {packet_external_id}")
            return
        
        document = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not document:
            print(f"[ERROR] No document found for packet {packet_external_id}")
            return
        
        # Use updated_extracted_fields if available, otherwise extracted_fields
        fields_dict = document.updated_extracted_fields or document.extracted_fields
        
        if not fields_dict:
            print(f"[ERROR] No extracted fields found for packet {packet_external_id}")
            return
        
        print(f"Re-validating packet: {packet_external_id}")
        print(f"  Current has_field_validation_errors: {packet.has_field_validation_errors}")
        
        # Re-validate
        validation_result = revalidate_packet(packet, document, fields_dict, db)
        
        if validation_result:
            db.commit()
            db.refresh(packet)
            
            print(f"  New has_field_validation_errors: {packet.has_field_validation_errors}")
            print(f"  Validation has_errors: {validation_result['has_errors']}")
            
            if validation_result['has_errors']:
                print("  Validation errors:")
                for field, errors in validation_result.get('field_errors', {}).items():
                    print(f"    - {field}: {', '.join(errors)}")
            else:
                print("  [OK] No validation errors!")
        else:
            print(f"  [ERROR] Failed to re-validate")
            
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        # Re-validate specific packet
        packet_id = sys.argv[1]
        revalidate_specific_packet(packet_id)
    else:
        # Re-validate all packets with N3941
        revalidate_all_packets_with_n3941()
