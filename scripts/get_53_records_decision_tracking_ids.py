"""
Script to get decision_tracking_ids for 53 records that need verification.

This script queries the database to find packets with duplicate decision records
or specific criteria, and outputs their decision_tracking_ids to a text file.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import SessionLocal


def get_packets_with_duplicate_decisions(limit: int = 53):
    """
    Find packets that have multiple decision records (potential duplicates).
    Returns decision_tracking_ids for these packets.
    """
    db = SessionLocal()
    try:
        query = text("""
            SELECT 
                p.decision_tracking_id,
                p.packet_id,
                p.external_id,
                COUNT(pd.packet_decision_id) as decision_count,
                STRING_AGG(pd.clinical_decision::TEXT, ', ' ORDER BY pd.created_at) as clinical_decisions,
                STRING_AGG(pd.operational_decision::TEXT, ', ' ORDER BY pd.created_at) as operational_decisions
            FROM service_ops.packet p
            LEFT JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
            WHERE p.decision_tracking_id IS NOT NULL
            GROUP BY p.packet_id, p.decision_tracking_id, p.external_id
            HAVING COUNT(pd.packet_decision_id) > 1
            ORDER BY decision_count DESC, p.created_at DESC
            LIMIT :limit
        """)
        
        result = db.execute(query, {"limit": limit})
        records = result.fetchall()
        
        return [
            {
                "decision_tracking_id": str(row.decision_tracking_id),
                "packet_id": row.packet_id,
                "external_id": row.external_id,
                "decision_count": row.decision_count,
                "clinical_decisions": row.clinical_decisions,
                "operational_decisions": row.operational_decisions
            }
            for row in records
        ]
    finally:
        db.close()


def get_packets_with_multiple_active_decisions(limit: int = 53):
    """
    Find packets that have multiple ACTIVE decision records (definite duplicates).
    Returns decision_tracking_ids for these packets.
    """
    db = SessionLocal()
    try:
        query = text("""
            SELECT 
                p.decision_tracking_id,
                p.packet_id,
                p.external_id,
                COUNT(pd.packet_decision_id) as active_decision_count
            FROM service_ops.packet p
            INNER JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
            WHERE p.decision_tracking_id IS NOT NULL
              AND pd.is_active = true
            GROUP BY p.packet_id, p.decision_tracking_id, p.external_id
            HAVING COUNT(pd.packet_decision_id) > 1
            ORDER BY active_decision_count DESC, p.created_at DESC
            LIMIT :limit
        """)
        
        result = db.execute(query, {"limit": limit})
        records = result.fetchall()
        
        return [
            {
                "decision_tracking_id": str(row.decision_tracking_id),
                "packet_id": row.packet_id,
                "external_id": row.external_id,
                "active_decision_count": row.active_decision_count
            }
            for row in records
        ]
    finally:
        db.close()


def get_all_packets(limit: int = None):
    """
    Get all decision_tracking_ids for all packets (or up to limit).
    """
    db = SessionLocal()
    try:
        if limit:
            query = text("""
                SELECT 
                    p.decision_tracking_id,
                    p.packet_id,
                    p.external_id,
                    COUNT(pd.packet_decision_id) as total_decision_count,
                    COUNT(CASE WHEN pd.is_active = true THEN 1 END) as active_decision_count,
                    MAX(pd.created_at) as last_decision_at
                FROM service_ops.packet p
                LEFT JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
                WHERE p.decision_tracking_id IS NOT NULL
                GROUP BY p.packet_id, p.decision_tracking_id, p.external_id
                ORDER BY p.created_at DESC
                LIMIT :limit
            """)
            result = db.execute(query, {"limit": limit})
        else:
            query = text("""
                SELECT 
                    p.decision_tracking_id,
                    p.packet_id,
                    p.external_id,
                    COUNT(pd.packet_decision_id) as total_decision_count,
                    COUNT(CASE WHEN pd.is_active = true THEN 1 END) as active_decision_count,
                    MAX(pd.created_at) as last_decision_at
                FROM service_ops.packet p
                LEFT JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
                WHERE p.decision_tracking_id IS NOT NULL
                GROUP BY p.packet_id, p.decision_tracking_id, p.external_id
                ORDER BY p.created_at DESC
            """)
            result = db.execute(query)
        
        records = result.fetchall()
        
        return [
            {
                "decision_tracking_id": str(row.decision_tracking_id),
                "packet_id": row.packet_id,
                "external_id": row.external_id,
                "total_decision_count": row.total_decision_count or 0,
                "active_decision_count": row.active_decision_count or 0,
                "last_decision_at": row.last_decision_at
            }
            for row in records
        ]
    finally:
        db.close()


def get_all_decision_tracking_ids_with_details(limit: int = 53):
    """
    Get decision_tracking_ids for packets with the most decision records.
    Useful for finding problematic records.
    """
    db = SessionLocal()
    try:
        query = text("""
            SELECT 
                p.decision_tracking_id,
                p.packet_id,
                p.external_id,
                COUNT(pd.packet_decision_id) as total_decision_count,
                COUNT(CASE WHEN pd.is_active = true THEN 1 END) as active_decision_count,
                MAX(pd.created_at) as last_decision_at
            FROM service_ops.packet p
            LEFT JOIN service_ops.packet_decision pd ON p.packet_id = pd.packet_id
            WHERE p.decision_tracking_id IS NOT NULL
            GROUP BY p.packet_id, p.decision_tracking_id, p.external_id
            ORDER BY total_decision_count DESC, active_decision_count DESC, p.created_at DESC
            LIMIT :limit
        """)
        
        result = db.execute(query, {"limit": limit})
        records = result.fetchall()
        
        return [
            {
                "decision_tracking_id": str(row.decision_tracking_id),
                "packet_id": row.packet_id,
                "external_id": row.external_id,
                "total_decision_count": row.total_decision_count or 0,
                "active_decision_count": row.active_decision_count or 0,
                "last_decision_at": row.last_decision_at
            }
            for row in records
        ]
    finally:
        db.close()


def save_to_text_file(decision_tracking_ids: list, output_file: str = "53_records_decision_tracking_ids.txt"):
    """Save decision_tracking_ids to a text file, one per line"""
    output_path = Path(__file__).parent / output_file
    
    with open(output_path, 'w') as f:
        f.write("# Decision Tracking IDs for 53 Records\n")
        f.write("# Generated by get_53_records_decision_tracking_ids.py\n")
        f.write("# Format: decision_tracking_id (packet_id, external_id, decision_count)\n\n")
        
        for record in decision_tracking_ids:
            if isinstance(record, dict):
                dt_id = record.get("decision_tracking_id", "")
                packet_id = record.get("packet_id", "N/A")
                external_id = record.get("external_id", "N/A")
                decision_count = record.get("decision_count") or record.get("total_decision_count") or record.get("active_decision_count") or "N/A"
                f.write(f"{dt_id} (packet_id: {packet_id}, external_id: {external_id}, decisions: {decision_count})\n")
            else:
                f.write(f"{record}\n")
    
    print(f"SUCCESS: Saved {len(decision_tracking_ids)} decision_tracking_ids to: {output_path}")
    return output_path


def main():
    """Main function to get and save decision_tracking_ids"""
    print("="*70)
    print("Getting Decision Tracking IDs for 53 Records")
    print("="*70)
    
    # Try different queries to find the 53 records
    print("\n1. Checking for packets with multiple decision records...")
    records1 = get_packets_with_duplicate_decisions(limit=53)
    print(f"   Found {len(records1)} packets with multiple decision records")
    
    print("\n2. Checking for packets with multiple ACTIVE decision records...")
    records2 = get_packets_with_multiple_active_decisions(limit=53)
    print(f"   Found {len(records2)} packets with multiple active decisions")
    
    print("\n3. Getting top packets by decision count...")
    records3 = get_all_decision_tracking_ids_with_details(limit=53)
    print(f"   Found {len(records3)} packets (sorted by decision count)")
    
    print("\n4. Getting ALL packets...")
    all_records = get_all_packets(limit=None)
    print(f"   Found {len(all_records)} total packets")
    
    # Use the query that returns closest to 53 records
    if len(all_records) >= 53:
        selected_records = all_records[:53]
        print(f"\nSUCCESS: Using first 53 packets from all packets: {len(selected_records)} records")
    elif len(records2) >= 53:
        selected_records = records2
        print(f"\nSUCCESS: Using packets with multiple ACTIVE decisions: {len(selected_records)} records")
    elif len(records1) >= 53:
        selected_records = records1
        print(f"\nSUCCESS: Using packets with multiple decisions: {len(selected_records)} records")
    else:
        selected_records = records3[:53] if len(records3) >= 53 else all_records
        print(f"\nSUCCESS: Using available packets: {len(selected_records)} records")
    
    # Extract just the decision_tracking_ids
    decision_tracking_ids = [r["decision_tracking_id"] for r in selected_records]
    
    # Save to text file
    output_file = save_to_text_file(selected_records)
    
    # Also save just the IDs (one per line, no comments)
    ids_only_file = Path(__file__).parent / "53_records_decision_tracking_ids_only.txt"
    with open(ids_only_file, 'w') as f:
        for dt_id in decision_tracking_ids:
            f.write(f"{dt_id}\n")
    
    print(f"SUCCESS: Saved IDs only to: {ids_only_file}")
    
    # Print summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Total decision_tracking_ids found: {len(decision_tracking_ids)}")
    print(f"\nFirst 5 decision_tracking_ids:")
    for i, record in enumerate(selected_records[:5], 1):
        print(f"  {i}. {record['decision_tracking_id']} (packet_id: {record['packet_id']}, decisions: {record.get('decision_count') or record.get('total_decision_count') or record.get('active_decision_count')})")
    
    print(f"\nSUCCESS: Files created:")
    print(f"  - {output_file}")
    print(f"  - {ids_only_file}")


if __name__ == '__main__':
    main()
