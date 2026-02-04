#!/usr/bin/env python3
"""
Diagnostic script to check if N3941 validation is working correctly
for a specific packet with procedure code 64561.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.services.field_validation_service import validate_all_fields, REQUIRED_DIAGNOSIS_PROCEDURES
import json

def check_n3941_validation(packet_external_id: str):
    """Check validation for a specific packet"""
    db = SessionLocal()
    try:
        packet = db.query(PacketDB).filter(PacketDB.external_id == packet_external_id).first()
        
        if not packet:
            print(f"[ERROR] Packet not found: {packet_external_id}")
            return
        
        print(f"[OK] Packet found: {packet_external_id}")
        print(f"   packet_id: {packet.packet_id}")
        
        # Get document
        document = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not document:
            print(f"[ERROR] No document found for packet {packet_external_id}")
            return
        
        print(f"\n=== CHECKING CODE CONFIGURATION ===")
        print(f"N3941 in vagus_nerve_stimulation codes: {'N3941' in REQUIRED_DIAGNOSIS_PROCEDURES['vagus_nerve_stimulation']['required_diagnosis_codes']}")
        print(f"Procedure code 64561 in vagus_nerve_stimulation: {'64561' in REQUIRED_DIAGNOSIS_PROCEDURES['vagus_nerve_stimulation']['procedure_codes']}")
        print(f"All required codes: {REQUIRED_DIAGNOSIS_PROCEDURES['vagus_nerve_stimulation']['required_diagnosis_codes']}")
        
        # Get extracted fields
        fields = document.updated_extracted_fields or document.extracted_fields
        if not fields:
            print(f"[ERROR] No extracted fields found")
            return
        
        print(f"\n=== EXTRACTED FIELDS ===")
        fields_dict = fields.get('fields', {})
        
        # Find diagnosis code
        diagnosis_code = None
        diagnosis_field_names = ['Diagnosis Codes', 'Diagnosis Code', 'Diagnosis codes', 'diagnosis_code']
        for field_name in diagnosis_field_names:
            if field_name in fields_dict:
                field_data = fields_dict[field_name]
                if isinstance(field_data, dict):
                    diagnosis_code = field_data.get('value', '')
                else:
                    diagnosis_code = str(field_data)
                if diagnosis_code:
                    print(f"   Diagnosis code found in '{field_name}': '{diagnosis_code}'")
                    break
        
        if not diagnosis_code:
            print(f"   [WARN] No diagnosis code found in fields")
        
        # Find procedure codes
        procedure_codes = []
        proc_field_names = ['Procedure Code set 1', 'Procedure Code 1', 'Procedure Code set 1', 'procedure_code_1']
        for field_name in proc_field_names:
            if field_name in fields_dict:
                field_data = fields_dict[field_name]
                if isinstance(field_data, dict):
                    proc_code = field_data.get('value', '')
                else:
                    proc_code = str(field_data)
                if proc_code:
                    procedure_codes.append(proc_code)
                    print(f"   Procedure code found in '{field_name}': '{proc_code}'")
        
        if not procedure_codes:
            print(f"   [WARN] No procedure codes found in fields")
        
        print(f"\n=== RUNNING VALIDATION ===")
        validation_result = validate_all_fields(
            extracted_fields=fields,
            packet=packet,
            db_session=db
        )
        
        print(f"   has_errors: {validation_result['has_errors']}")
        print(f"   field_errors: {json.dumps(validation_result.get('field_errors', {}), indent=2)}")
        
        # Check specifically for diagnosis_code errors
        if 'diagnosis_code' in validation_result.get('field_errors', {}):
            errors = validation_result['field_errors']['diagnosis_code']
            print(f"\n   [ERROR] Diagnosis code validation errors found:")
            for error in errors:
                print(f"      - {error}")
        else:
            print(f"\n   [OK] No diagnosis code validation errors")
        
        print(f"\n=== SUMMARY ===")
        if diagnosis_code and 'N3941' in diagnosis_code.upper().replace('.', ''):
            if validation_result['has_errors'] and 'diagnosis_code' in validation_result.get('field_errors', {}):
                print(f"[ERROR] ISSUE: N3941 is being rejected even though it's in the allowed list")
                print(f"   This suggests the backend service needs to be restarted to load the new code")
            else:
                print(f"[OK] N3941 validation is working correctly")
        else:
            print(f"[INFO] Diagnosis code is not N3941, or not found")
        
    finally:
        db.close()

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        packet_id = sys.argv[1]
    else:
        # Default to the packet from the screenshot
        packet_id = 'SVC-2026-975319'
    
    check_n3941_validation(packet_id)
