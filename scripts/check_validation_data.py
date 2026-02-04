#!/usr/bin/env python3
"""Check validation data for a test packet"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.packet_validation_db import PacketValidationDB
from app.utils.packet_converter import packet_to_dto
import json

def check_packet(external_id: str):
    db = SessionLocal()
    try:
        p = db.query(PacketDB).filter(PacketDB.external_id == external_id).first()
        if not p:
            print(f"❌ Packet {external_id} not found")
            return
        
        print(f"[OK] Packet found: {external_id}")
        print(f"   packet_id: {p.packet_id}")
        print(f"   has_field_validation_errors: {p.has_field_validation_errors} (type: {type(p.has_field_validation_errors)})")
        
        # Check validation table
        print("\n=== VALIDATION TABLE ===")
        validations = db.query(PacketValidationDB).filter(
            PacketValidationDB.packet_id == p.packet_id
        ).order_by(PacketValidationDB.created_at.desc()).all()
        
        print(f"Found {len(validations)} validation records")
        for i, v in enumerate(validations[:3], 1):
            print(f"\n  Record {i}:")
            print(f"    packet_validation_id: {v.packet_validation_id}")
            print(f"    validation_type: {v.validation_type}")
            print(f"    validation_status: {v.validation_status}")
            if v.validation_result:
                result_str = json.dumps(v.validation_result, default=str, indent=6)
                print(f"    validation_result: {result_str[:500]}")
        
        # Check DTO conversion
        print("\n=== DTO CONVERSION ===")
        dto = packet_to_dto(p, db_session=db)
        print(f"hasFieldValidationErrors: {dto.hasFieldValidationErrors} (type: {type(dto.hasFieldValidationErrors)})")
        print(f"fieldValidationErrors: {dto.fieldValidationErrors}")
        
        # Check serialization
        print("\n=== SERIALIZATION ===")
        if hasattr(dto, 'model_dump'):
            dto_dict = dto.model_dump(exclude_none=False, mode='json')
        else:
            dto_dict = dto.dict(exclude_none=False)
        
        print(f"hasFieldValidationErrors in dict: {'hasFieldValidationErrors' in dto_dict}")
        print(f"fieldValidationErrors in dict: {'fieldValidationErrors' in dto_dict}")
        if 'hasFieldValidationErrors' in dto_dict:
            print(f"  Value: {dto_dict['hasFieldValidationErrors']}")
        if 'fieldValidationErrors' in dto_dict:
            print(f"  Value: {dto_dict['fieldValidationErrors']}")
        
        # Show last 5 keys
        keys = list(dto_dict.keys())
        print(f"\nLast 5 keys in DTO: {keys[-5:]}")
        
    finally:
        db.close()

if __name__ == '__main__':
    check_packet('TEST-ERRORS-1769633369')
