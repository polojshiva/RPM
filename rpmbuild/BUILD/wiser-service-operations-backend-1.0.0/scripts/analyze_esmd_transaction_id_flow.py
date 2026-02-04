"""
Analyze esmdTransactionId flow from integration.send_serviceops to packet table
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text

def analyze_esmd_transaction_id():
    db = SessionLocal()
    try:
        # 1. Check where esmdTransactionId is in integration.send_serviceops payload
        print("=" * 80)
        print("1. ESMD Transaction ID in integration.send_serviceops (ESMD channel only)")
        print("=" * 80)
        
        query1 = text("""
            SELECT 
                message_id,
                channel_type_id,
                payload->'submission_metadata'->>'esmdTransactionId' as esmd_txn_id_new,
                payload->'submission_metadata'->>'esmd_transaction_id' as esmd_txn_id_alt,
                payload->'ingest_data'->>'esmd_transaction_id' as esmd_txn_id_old
            FROM integration.send_serviceops
            WHERE channel_type_id = 3  -- ESMD channel
            ORDER BY message_id DESC
            LIMIT 10
        """)
        
        result1 = db.execute(query1)
        rows1 = result1.fetchall()
        
        if rows1:
            for row in rows1:
                esmd_id = row[2] or row[3] or row[4] or "NOT FOUND"
                print(f"  message_id={row[0]}, channel={row[1]}, esmdTransactionId={esmd_id}")
        else:
            print("  No ESMD messages found")
        
        # 2. Check packet.case_id usage by channel
        print("\n" + "=" * 80)
        print("2. Packet case_id by Channel Type")
        print("=" * 80)
        
        query2 = text("""
            SELECT 
                channel_type_id,
                COUNT(*) as total,
                COUNT(case_id) as with_case_id,
                COUNT(*) FILTER (WHERE case_id IS NOT NULL) as not_null_count
            FROM service_ops.packet
            WHERE channel_type_id IN (1, 2, 3)
            GROUP BY channel_type_id
            ORDER BY channel_type_id
        """)
        
        result2 = db.execute(query2)
        rows2 = result2.fetchall()
        
        channel_names = {1: "Portal", 2: "Fax", 3: "ESMD"}
        for row in rows2:
            channel_name = channel_names.get(row[0], f"Unknown({row[0]})")
            print(f"  {channel_name} (channel_type_id={row[0]}):")
            print(f"    Total packets: {row[1]}")
            print(f"    With case_id: {row[2]}")
            print(f"    case_id NULL: {row[1] - row[2]}")
        
        # 3. Sample packets showing case_id values
        print("\n" + "=" * 80)
        print("3. Sample Packets - case_id Values")
        print("=" * 80)
        
        query3 = text("""
            SELECT 
                p.packet_id,
                p.external_id,
                p.case_id,
                p.channel_type_id,
                s.payload->'submission_metadata'->>'esmdTransactionId' as esmd_txn_id
            FROM service_ops.packet p
            LEFT JOIN integration.send_serviceops s 
                ON p.decision_tracking_id::text = s.decision_tracking_id
            WHERE p.channel_type_id IN (1, 3)
            ORDER BY p.channel_type_id, p.packet_id DESC
            LIMIT 10
        """)
        
        result3 = db.execute(query3)
        rows3 = result3.fetchall()
        
        for row in rows3:
            channel_name = channel_names.get(row[3], f"Unknown({row[3]})")
            case_id_display = row[2] if row[2] else "NULL"
            esmd_id_display = row[4] if row[4] else "N/A"
            print(f"  {channel_name}: packet_id={row[0]}, external_id={row[1]}, case_id={case_id_display}, esmdTransactionId={esmd_id_display}")
        
        # 4. Check if esmdTransactionId exists in extracted_fields
        print("\n" + "=" * 80)
        print("4. esmdTransactionId in packet_document.extracted_fields")
        print("=" * 80)
        
        query4 = text("""
            SELECT 
                pd.packet_id,
                pd.extracted_fields->>'esmd_transaction_id' as esmd_in_extracted,
                pd.extracted_fields->>'esmdTransactionId' as esmd_in_extracted_alt,
                p.channel_type_id
            FROM service_ops.packet_document pd
            JOIN service_ops.packet p ON pd.packet_id = p.packet_id
            WHERE p.channel_type_id = 3  -- ESMD only
            AND (pd.extracted_fields ? 'esmd_transaction_id' OR pd.extracted_fields ? 'esmdTransactionId')
            LIMIT 5
        """)
        
        result4 = db.execute(query4)
        rows4 = result4.fetchall()
        
        if rows4:
            for row in rows4:
                esmd_in_extracted = row[1] or row[2] or "NOT FOUND"
                print(f"  packet_id={row[0]}, esmdTransactionId in extracted_fields={esmd_in_extracted}")
        else:
            print("  No esmdTransactionId found in extracted_fields for ESMD packets")
        
        # 5. Summary and recommendation
        print("\n" + "=" * 80)
        print("5. Analysis Summary")
        print("=" * 80)
        print("""
        Current State:
        - esmdTransactionId is in integration.send_serviceops.payload.submission_metadata
        - It's extracted by PayloadParser._extract_esmd_transaction_id()
        - It's passed to DocumentProcessor._get_or_create_packet() as parameter
        - BUT: It's NOT stored in packet table anywhere
        - Currently: case_id is only populated for Portal (from payload.packet_id)
        - ESMD and Fax have case_id = NULL
        
        Recommendation:
        - For ESMD channel (channel_type_id=3): Store esmdTransactionId in packet.case_id
        - This gives ESMD cases a channel-specific identifier (like Portal has)
        - Flow: integration.send_serviceops.payload.submission_metadata.esmdTransactionId 
                → packet.case_id (for ESMD only)
        - This would be similar to Portal: payload.packet_id → packet.case_id
        """)
        
    finally:
        db.close()

if __name__ == "__main__":
    analyze_esmd_transaction_id()

