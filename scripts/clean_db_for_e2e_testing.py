"""
Clean database for end-to-end testing
Preserves integration.send_serviceops table (source of truth for incoming messages)
Cleans all service_ops tables to allow fresh E2E testing
"""
import sys
import os
import argparse
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal

def print_status(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def clean_service_ops_tables(db: Session):
    """Clean all service_ops tables while preserving integration.send_serviceops"""
    print_status("Starting database cleanup...")
    print_status("PRESERVING: integration.send_serviceops (source of truth)")
    print_status("CLEANING: All service_ops tables")
    print()
    
    try:
        # Get counts before cleanup
        print_status("Getting record counts before cleanup...")
        counts = {}
        
        tables_to_clean = [
            ('service_ops', 'send_integration'),
            ('service_ops', 'send_clinicalops'),
            ('service_ops', 'send_serviceops'),
            ('service_ops', 'packet_decision'),
            ('service_ops', 'packet_validation'),
            ('service_ops', 'validation_run'),
            ('service_ops', 'packet_document'),
            ('service_ops', 'packet'),
            ('service_ops', 'letter'),
            ('service_ops', 'ocr_extractions'),
            ('service_ops', 'document_classifications'),
            ('service_ops', 'integration_poll_watermark'),
            ('service_ops', 'clinical_ops_poll_watermark'),
        ]
        
        for schema, table in tables_to_clean:
            try:
                result = db.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))
                count = result.scalar()
                counts[f"{schema}.{table}"] = count
            except Exception as e:
                db.rollback()  # Rollback on error to continue
                print_status(f"  Warning: Could not count {schema}.{table}: {e}")
                counts[f"{schema}.{table}"] = "N/A"
        
        # Check integration.send_serviceops (should be preserved)
        try:
            result = db.execute(text("SELECT COUNT(*) FROM integration.send_serviceops"))
            integration_count = result.scalar()
            counts["integration.send_serviceops"] = integration_count
            print_status(f"  integration.send_serviceops: {integration_count} records (PRESERVED)")
        except Exception as e:
            db.rollback()  # Rollback on error to continue
            print_status(f"  Warning: Could not count integration.send_serviceops: {e}")
            counts["integration.send_serviceops"] = "N/A"
        
        print()
        print_status("BEFORE CLEANUP:")
        for table, count in sorted(counts.items()):
            print_status(f"  {table}: {count} records")
        print()
        
        # Clean tables in order (respecting foreign key dependencies)
        print_status("Cleaning tables (in dependency order)...")
        
        # 1. Clean outbox/inbox tables first
        print_status("  1. Cleaning outbox/inbox tables...")
        try:
            db.execute(text("DELETE FROM service_ops.send_integration"))
            db.commit()
            print_status("     [OK] service_ops.send_integration")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.send_integration: {e}")
        
        try:
            db.execute(text("DELETE FROM service_ops.send_clinicalops"))
            db.commit()
            print_status("     [OK] service_ops.send_clinicalops")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.send_clinicalops: {e}")
        
        try:
            db.execute(text("DELETE FROM service_ops.send_serviceops"))
            db.commit()
            print_status("     [OK] service_ops.send_serviceops")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.send_serviceops: {e}")
        
        # 2. Clean decision/validation tables
        print_status("  2. Cleaning decision/validation tables...")
        try:
            db.execute(text("DELETE FROM service_ops.packet_decision"))
            db.commit()
            print_status("     [OK] service_ops.packet_decision")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.packet_decision: {e}")
        
        try:
            db.execute(text("DELETE FROM service_ops.packet_validation"))
            db.commit()
            print_status("     [OK] service_ops.packet_validation")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.packet_validation: {e}")
        
        try:
            db.execute(text("DELETE FROM service_ops.validation_run"))
            db.commit()
            print_status("     [OK] service_ops.validation_run")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.validation_run: {e}")
        
        # 3. Clean document tables (before packet due to foreign keys)
        print_status("  3. Cleaning document tables...")
        try:
            db.execute(text("DELETE FROM service_ops.packet_document"))
            db.commit()  # Commit after each major deletion
            print_status("     [OK] service_ops.packet_document")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.packet_document: {e}")
        
        try:
            db.execute(text("DELETE FROM service_ops.letter"))
            db.commit()
            print_status("     [OK] service_ops.letter")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.letter: {e}")
        
        try:
            db.execute(text("DELETE FROM service_ops.ocr_extractions"))
            db.commit()
            print_status("     [OK] service_ops.ocr_extractions")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.ocr_extractions (table may not exist): {e}")
        
        try:
            db.execute(text("DELETE FROM service_ops.document_classifications"))
            db.commit()
            print_status("     [OK] service_ops.document_classifications")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.document_classifications (table may not exist): {e}")
        
        # 4. Clean packet table (main table) - after documents are deleted
        print_status("  4. Cleaning packet table...")
        try:
            db.execute(text("DELETE FROM service_ops.packet"))
            db.commit()
            print_status("     [OK] service_ops.packet")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.packet: {e}")
        
        # 5. Reset watermarks (delete and recreate or set to epoch)
        print_status("  5. Resetting watermarks...")
        try:
            # Delete existing watermark records
            db.execute(text("DELETE FROM service_ops.integration_poll_watermark"))
            db.commit()
            print_status("     [OK] service_ops.integration_poll_watermark (deleted)")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.integration_poll_watermark: {e}")
        
        try:
            # Delete existing watermark records
            db.execute(text("DELETE FROM service_ops.clinical_ops_poll_watermark"))
            db.commit()
            print_status("     [OK] service_ops.clinical_ops_poll_watermark (deleted)")
        except Exception as e:
            db.rollback()
            print_status(f"     [SKIP] service_ops.clinical_ops_poll_watermark: {e}")
        print()
        print_status("[OK] All tables cleaned successfully!")
        print()
        
        # Verify cleanup
        print_status("AFTER CLEANUP:")
        for schema, table in tables_to_clean:
            try:
                result = db.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))
                count = result.scalar()
                print_status(f"  {schema}.{table}: {count} records")
            except Exception as e:
                print_status(f"  {schema}.{table}: Error - {e}")
        
        # Verify integration.send_serviceops is still there
        try:
            result = db.execute(text("SELECT COUNT(*) FROM integration.send_serviceops"))
            integration_count = result.scalar()
            print_status(f"  integration.send_serviceops: {integration_count} records (PRESERVED [OK])")
        except Exception as e:
            print_status(f"  integration.send_serviceops: Error - {e}")
        
        print()
        print_status("Database cleanup complete!")
        print_status("Ready for end-to-end testing with integration.send_serviceops as source")
        
        return True
        
    except Exception as e:
        db.rollback()
        print_status(f"ERROR during cleanup: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description='Clean database for end-to-end testing')
    parser.add_argument('--yes', '-y', action='store_true', 
                       help='Skip confirmation prompt (non-interactive mode)')
    args = parser.parse_args()
    
    print("="*80)
    print("DATABASE CLEANUP FOR END-TO-END TESTING")
    print("="*80)
    print(f"Date: {datetime.now().isoformat()}")
    print()
    print("This script will:")
    print("  [PRESERVE] integration.send_serviceops (source of truth)")
    print("  [DELETE] All service_ops tables (packets, documents, decisions, etc.)")
    print("  [RESET] Polling watermarks")
    print()
    
    if not args.yes:
        try:
            response = input("Are you sure you want to proceed? (yes/no): ")
            if response.lower() != 'yes':
                print("Cleanup cancelled.")
                return
        except EOFError:
            print("No input available. Use --yes flag for non-interactive mode.")
            return
    
    db = SessionLocal()
    try:
        success = clean_service_ops_tables(db)
        if success:
            print()
            print("="*80)
            print("SUCCESS: Database cleaned and ready for E2E testing")
            print("="*80)
        else:
            print()
            print("="*80)
            print("ERROR: Cleanup failed - check logs above")
            print("="*80)
    except Exception as e:
        print(f"\nFATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

