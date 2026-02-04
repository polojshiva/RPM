#!/usr/bin/env python3
"""
PRODUCTION-SAFE: Re-validate all packets that currently have validation errors.
This will re-run validation with the latest code (including N3941 fix, city validation fix, etc.)

This script is safe to run in production:
- Only re-validates packets that already have validation errors
- Creates new validation records (doesn't delete old ones - maintains audit trail)
- Handles errors gracefully and continues processing
- Provides detailed logging
- Can be run multiple times safely (idempotent)

Usage:
    # Re-validate all packets with errors
    python scripts/revalidate_all_packets_with_errors.py
    
    # Re-validate specific packet
    python scripts/revalidate_all_packets_with_errors.py <packet_id>
    
    # Dry run (show what would be re-validated without making changes)
    python scripts/revalidate_all_packets_with_errors.py --dry-run
"""
import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.services.field_validation_service import validate_all_fields
from app.services.validation_persistence import save_field_validation_errors, update_packet_validation_flag
from sqlalchemy import and_
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def revalidate_packet(packet, document, fields_dict, db, dry_run=False):
    """Re-validate a single packet"""
    try:
        if dry_run:
            logger.info(f"  [DRY RUN] Would re-validate packet {packet.external_id}")
            return None
        
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
        logger.error(f"Error re-validating packet {packet.external_id}: {e}", exc_info=True)
        return None


def revalidate_all_packets_with_errors(dry_run=False, specific_packet_id=None):
    """Re-validate all packets that currently have validation errors"""
    db = SessionLocal()
    try:
        print("=" * 80)
        if dry_run:
            print("DRY RUN: Re-validating packets with validation errors (no changes will be made)")
        else:
            print("Re-validating packets with validation errors")
        print("=" * 80)
        
        # Find all packets with validation errors
        if specific_packet_id:
            packets = db.query(PacketDB).filter(
                PacketDB.external_id == specific_packet_id,
                PacketDB.has_field_validation_errors == True
            ).all()
            if not packets:
                print(f"[WARN] Packet {specific_packet_id} not found or does not have validation errors")
                return
        else:
            packets = db.query(PacketDB).filter(
                PacketDB.has_field_validation_errors == True
            ).all()
        
        if not packets:
            print("\n[INFO] No packets found with validation errors")
            return
        
        print(f"\nFound {len(packets)} packet(s) with validation errors to re-validate")
        
        if dry_run:
            print("\n[DRY RUN MODE] No changes will be made to the database")
        
        # Re-validate each packet
        fixed_count = 0
        still_has_errors_count = 0
        error_count = 0
        
        for packet in packets:
            print(f"\nProcessing: {packet.external_id} (packet_id: {packet.packet_id})")
            
            # Get document
            document = db.query(PacketDocumentDB).filter(
                PacketDocumentDB.packet_id == packet.packet_id
            ).first()
            
            if not document:
                print(f"  [WARN] No document found, skipping")
                error_count += 1
                continue
            
            # Use updated_extracted_fields if available, otherwise extracted_fields
            fields_dict = document.updated_extracted_fields or document.extracted_fields
            
            if not fields_dict:
                print(f"  [WARN] No extracted fields found, skipping")
                error_count += 1
                continue
            
            # Get current validation status
            old_has_errors = packet.has_field_validation_errors
            
            # Re-validate
            validation_result = revalidate_packet(packet, document, fields_dict, db, dry_run=dry_run)
            
            if validation_result:
                if not dry_run:
                    db.commit()
                    db.refresh(packet)
                
                new_has_errors = validation_result['has_errors']
                
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
            elif not dry_run:
                error_count += 1
                db.rollback()
        
        print("\n" + "=" * 80)
        print("Re-validation complete!")
        print("=" * 80)
        print(f"Total packets processed: {len(packets)}")
        print(f"Fixed (errors cleared): {fixed_count}")
        print(f"Still has errors: {still_has_errors_count}")
        print(f"Errors (failed to process): {error_count}")
        print(f"No errors (already correct): {len(packets) - fixed_count - still_has_errors_count - error_count}")
        
        if dry_run:
            print("\n[DRY RUN] No changes were made. Run without --dry-run to apply changes.")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error during re-validation: {e}", exc_info=True)
        print(f"\n[ERROR] {str(e)}")
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description='Re-validate packets with validation errors using latest validation code'
    )
    parser.add_argument(
        'packet_id',
        nargs='?',
        help='Optional: Specific packet ID to re-validate (external_id)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode: Show what would be re-validated without making changes'
    )
    
    args = parser.parse_args()
    
    revalidate_all_packets_with_errors(
        dry_run=args.dry_run,
        specific_packet_id=args.packet_id
    )


if __name__ == "__main__":
    main()
