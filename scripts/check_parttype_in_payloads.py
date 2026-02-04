#!/usr/bin/env python3
"""Check partType in send_serviceops payloads"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text
import json

def check_parttype_in_payloads():
    db = SessionLocal()
    try:
        # Query all records with json_sent_to_integration = true
        query = text("""
            SELECT 
                message_id,
                decision_tracking_id,
                payload,
                json_sent_to_integration,
                created_at
            FROM service_ops.send_serviceops
            WHERE json_sent_to_integration = true
                AND is_deleted = false
            ORDER BY created_at DESC
            LIMIT 100
        """)
        
        result = db.execute(query).fetchall()
        
        total = len(result)
        has_parttype = 0
        missing_parttype = 0
        parttype_a = 0
        parttype_b = 0
        parttype_empty = 0
        
        print(f"Total records with json_sent_to_integration=true: {total}\n")
        
        for row in result:
            message_id = row[0]
            decision_tracking_id = row[1]
            payload = row[2]
            created_at = row[4]
            
            if payload and isinstance(payload, dict):
                part_type = payload.get('partType', '')
                
                if part_type:
                    has_parttype += 1
                    part_type_upper = part_type.strip().upper()
                    if part_type_upper == 'A':
                        parttype_a += 1
                    elif part_type_upper == 'B':
                        parttype_b += 1
                    else:
                        print(f"  Message {message_id}: partType='{part_type}' (unexpected value)")
                else:
                    missing_parttype += 1
                    print(f"  Message {message_id} ({decision_tracking_id}): partType is empty or missing")
            else:
                missing_parttype += 1
                print(f"  Message {message_id} ({decision_tracking_id}): payload is empty or invalid")
        
        print(f"\n=== SUMMARY ===")
        print(f"Total records: {total}")
        print(f"Has partType: {has_parttype}")
        print(f"  - partType='A': {parttype_a}")
        print(f"  - partType='B': {parttype_b}")
        print(f"Missing partType: {missing_parttype}")
        print(f"Missing percentage: {(missing_parttype/total*100) if total > 0 else 0:.1f}%")
        
    finally:
        db.close()

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    check_parttype_in_payloads()
