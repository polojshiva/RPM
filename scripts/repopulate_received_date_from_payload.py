"""
Script to repopulate packet.received_date with raw timestamps from original payloads.

This script:
1. Finds all packets with received_date normalized to midnight (00:00:00)
2. Joins with integration.send_serviceops to get original payload
3. Extracts submission date from payload (same logic as DocumentProcessor)
4. Updates packet.received_date with raw timestamp (preserving original time)

Usage:
    python scripts/repopulate_received_date_from_payload.py [--dry-run] [--limit N]
    
Options:
    --dry-run: Preview changes without updating database
    --limit N: Process only first N packets (for testing)
"""
import os
import sys
import argparse
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dateutil import parser

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Get database URL
database_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
if not database_url:
    print("ERROR: DATABASE_URL or POSTGRES_URL environment variable not set")
    sys.exit(1)

# Create database connection
engine = create_engine(database_url)
Session = sessionmaker(bind=engine)
db = Session()


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse ISO 8601 date string and return raw timestamp (no normalization).
    Same logic as DocumentProcessor._parse_date()
    """
    if not date_str or not isinstance(date_str, str):
        return None
    
    try:
        # Parse the date string
        parsed_date = parser.parse(date_str)
        
        # Ensure timezone-aware (convert to UTC if needed)
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
        else:
            parsed_date = parsed_date.astimezone(timezone.utc)
        
        # Return raw timestamp (no normalization to midnight)
        return parsed_date
    
    except Exception as e:
        print(f"    Warning: Failed to parse date '{date_str}': {e}")
        return None


def extract_submission_date_from_payload(
    payload: Dict[str, Any],
    channel_type_id: Optional[int]
) -> Optional[datetime]:
    """
    Extract submission date from payload based on channel type.
    Same logic as DocumentProcessor._extract_submission_date_from_payload()
    """
    if not channel_type_id:
        return None
    
    submission_date_str = None
    
    try:
        # ESMD: Extract from submission_metadata.creationTime
        if channel_type_id == 3:  # ESMD
            submission_metadata = payload.get('submission_metadata', {})
            if isinstance(submission_metadata, dict):
                submission_date_str = submission_metadata.get('creationTime')
        
        # Portal: Extract from ocr.fields["Submitted Date"].value
        elif channel_type_id == 1:  # Portal
            if payload and isinstance(payload, dict):
                ocr_data = payload.get('ocr', {})
                if isinstance(ocr_data, dict):
                    fields = ocr_data.get('fields', {})
                    if isinstance(fields, dict):
                        submitted_date_field = fields.get('Submitted Date', {})
                        if isinstance(submitted_date_field, dict):
                            submission_date_str = submitted_date_field.get('value')
        
        # Fax: Extract from submission_metadata.creationTime
        elif channel_type_id == 2:  # Fax
            submission_metadata = payload.get('submission_metadata', {})
            if isinstance(submission_metadata, dict):
                submission_date_str = submission_metadata.get('creationTime')
            
            # Fallback: Try extracted_fields.fields["Submitted Date"].value (after OCR)
            if not submission_date_str:
                extracted_fields = payload.get('extracted_fields', {})
                if isinstance(extracted_fields, dict):
                    fields = extracted_fields.get('fields', {})
                    if isinstance(fields, dict):
                        submitted_date_field = fields.get('Submitted Date', {})
                        if isinstance(submitted_date_field, dict):
                            submission_date_str = submitted_date_field.get('value')
        
        # Parse the date string if found (returns raw timestamp, no normalization)
        if submission_date_str:
            return parse_date(submission_date_str)
    
    except Exception as e:
        print(f"    Warning: Failed to extract submission date: {e}")
    
    return None


def repopulate_received_dates(dry_run: bool = False, limit: Optional[int] = None):
    """
    Repopulate packet.received_date with raw timestamps from original payloads.
    """
    print("=" * 80)
    print("REPOPULATING RECEIVED_DATE FROM ORIGINAL PAYLOADS")
    print("=" * 80)
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else 'LIVE (will update database)'}")
    if limit:
        print(f"Limit: Processing first {limit} packets")
    print("=" * 80)
    
    # Find packets with received_date at midnight (normalized)
    # Join with integration.send_serviceops to get original payload
    query = """
        SELECT 
            p.packet_id,
            p.external_id,
            p.decision_tracking_id,
            p.received_date as current_received_date,
            p.channel_type_id,
            EXTRACT(HOUR FROM p.received_date) as current_hour,
            EXTRACT(MINUTE FROM p.received_date) as current_minute,
            EXTRACT(SECOND FROM p.received_date) as current_second,
            s.payload,
            s.created_at as message_created_at
        FROM service_ops.packet p
        INNER JOIN integration.send_serviceops s
            ON p.decision_tracking_id::text = s.decision_tracking_id::text
        WHERE 
            -- Only process packets with midnight times (normalized)
            (EXTRACT(HOUR FROM p.received_date) = 0 
             AND EXTRACT(MINUTE FROM p.received_date) = 0 
             AND EXTRACT(SECOND FROM p.received_date) = 0)
            AND s.is_deleted = false
            AND s.payload IS NOT NULL
        ORDER BY p.packet_id
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    result = db.execute(text(query))
    rows = result.fetchall()
    
    print(f"\nFound {len(rows)} packets with normalized received_date (midnight times)")
    print("-" * 80)
    
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    for i, row in enumerate(rows, 1):
        packet_id = row.packet_id
        external_id = row.external_id
        decision_tracking_id = row.decision_tracking_id
        current_received_date = row.current_received_date
        channel_type_id = row.channel_type_id
        payload = row.payload
        message_created_at = row.message_created_at
        
        print(f"\n[{i}/{len(rows)}] Processing packet: {external_id} (ID: {packet_id})")
        print(f"  Current received_date: {current_received_date}")
        print(f"  Channel type: {channel_type_id} ({'Portal' if channel_type_id == 1 else 'Fax' if channel_type_id == 2 else 'ESMD' if channel_type_id == 3 else 'Unknown'})")
        
        # Extract submission date from payload
        extracted_date = extract_submission_date_from_payload(payload, channel_type_id)
        
        if extracted_date:
            new_received_date = extracted_date
            source = "payload"
            print(f"  Extracted from payload: {new_received_date}")
        elif message_created_at:
            # Fallback to message.created_at
            new_received_date = message_created_at
            if new_received_date.tzinfo is None:
                new_received_date = new_received_date.replace(tzinfo=timezone.utc)
            source = "message.created_at"
            print(f"  Using message.created_at: {new_received_date}")
        else:
            print(f"  [SKIP] No submission date found in payload and no message.created_at")
            skipped_count += 1
            continue
        
        # Check if the new date is different from current
        if new_received_date == current_received_date:
            print(f"  [SKIP] New date same as current date (already correct)")
            skipped_count += 1
            continue
        
        # Check if new date has non-midnight time
        if new_received_date.hour == 0 and new_received_date.minute == 0 and new_received_date.second == 0:
            print(f"  [SKIP] New date is also at midnight (no time information available)")
            skipped_count += 1
            continue
        
        print(f"  New received_date: {new_received_date} (source: {source})")
        print(f"  Time difference: {new_received_date.hour}:{new_received_date.minute}:{new_received_date.second}")
        
        if not dry_run:
            try:
                # Update packet.received_date
                update_query = text("""
                    UPDATE service_ops.packet
                    SET received_date = :new_received_date,
                        updated_at = :updated_at
                    WHERE packet_id = :packet_id
                """)
                
                db.execute(update_query, {
                    "new_received_date": new_received_date,
                    "updated_at": datetime.now(timezone.utc),
                    "packet_id": packet_id
                })
                
                db.commit()
                print(f"  [UPDATED] Successfully updated packet.received_date")
                updated_count += 1
            except Exception as e:
                db.rollback()
                print(f"  [ERROR] Failed to update: {e}")
                error_count += 1
        else:
            print(f"  [DRY RUN] Would update packet.received_date")
            updated_count += 1
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total packets processed: {len(rows)}")
    print(f"Updated: {updated_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Errors: {error_count}")
    print("=" * 80)
    
    if dry_run:
        print("\nThis was a DRY RUN. No changes were made to the database.")
        print("Run without --dry-run to apply changes.")
    else:
        print("\nRepopulation complete!")
        print("\nNote: New packets will automatically store raw timestamps.")
        print("This script only updates existing packets that were normalized to midnight.")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Repopulate packet.received_date with raw timestamps from original payloads"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without updating database'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Process only first N packets (for testing)'
    )
    
    args = parser.parse_args()
    
    try:
        repopulate_received_dates(dry_run=args.dry_run, limit=args.limit)
        return 0
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
