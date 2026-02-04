#!/usr/bin/env python3
"""Check part_type in packet documents for records with missing partType in payload"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text

def check_parttype_in_packets():
    db = SessionLocal()
    try:
        # Get records with json_sent_to_integration = true and check their packet documents
        query = text("""
            SELECT 
                s.message_id,
                s.decision_tracking_id,
                s.payload->>'partType' as payload_parttype,
                p.packet_id,
                pd.part_type as document_part_type
            FROM service_ops.send_serviceops s
            JOIN service_ops.packet p ON p.decision_tracking_id = s.decision_tracking_id::uuid
            LEFT JOIN service_ops.packet_document pd ON pd.packet_id = p.packet_id
            WHERE s.json_sent_to_integration = true
                AND s.is_deleted = false
            ORDER BY s.created_at DESC
        """)
        
        result = db.execute(query).fetchall()
        
        print(f"Checking {len(result)} records...\n")
        
        for row in result:
            message_id = row[0]
            decision_tracking_id = row[1]
            payload_parttype = row[2]
            packet_id = row[3]
            document_part_type = row[4]
            
            print(f"Message {message_id} ({decision_tracking_id}):")
            print(f"  Payload partType: '{payload_parttype}' (empty if NULL)")
            print(f"  Document part_type: '{document_part_type}' (empty if NULL)")
            print()
        
        # Summary
        has_doc_parttype = sum(1 for row in result if row[4])
        missing_both = sum(1 for row in result if not row[2] and not row[4])
        
        print(f"=== SUMMARY ===")
        print(f"Total records: {len(result)}")
        print(f"Has part_type in document: {has_doc_parttype}")
        print(f"Missing both (payload + document): {missing_both}")
        
    finally:
        db.close()

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    check_parttype_in_packets()
