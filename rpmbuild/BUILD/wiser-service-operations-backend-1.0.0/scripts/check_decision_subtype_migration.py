#!/usr/bin/env python3
"""
Check if decision_subtype column exists in packet_decision table

This script verifies if migration 012 (or STAGE_1_UTN_WORKFLOW_MIGRATIONS) has been applied.
"""

import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

def get_db_url():
    """Get database URL from environment"""
    return os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')

def check_decision_subtype_column():
    """Check if decision_subtype column exists"""
    
    print("=" * 80)
    print("CHECKING: decision_subtype column in packet_decision table")
    print("=" * 80)
    print()
    
    # Get database URL
    db_url = get_db_url()
    if not db_url:
        print("ERROR: Database URL not configured. Check DATABASE_URL environment variable.")
        return False
    
    try:
        # Create engine and session
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        db = Session()
        
        # Check if decision_subtype column exists
        check_query = text("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_schema = 'service_ops' 
                AND table_name = 'packet_decision' 
                AND column_name = 'decision_subtype'
            ) AS column_exists
        """)
        
        result = db.execute(check_query).first()
        column_exists = result[0] if result else False
        
        print(f"✓ decision_subtype column exists: {column_exists}")
        print()
        
        if column_exists:
            print("✅ PASS: Migration 012 has been applied.")
            print("   The decision_subtype column exists in the database.")
            print("   Code will work normally without fallback error handling.")
        else:
            print("⚠️  FAIL: Migration 012 has NOT been applied.")
            print("   The decision_subtype column does NOT exist in the database.")
            print("   Code will use fallback error handling (raw SQL) until migration is applied.")
            print()
            print("   To apply the migration, run:")
            print("   - deploy/migrations/012_extend_packet_decision_for_utn_workflow.sql")
            print("   OR")
            print("   - deploy/migrations/STAGE_1_UTN_WORKFLOW_MIGRATIONS.sql")
        
        print()
        
        # Check all UTN workflow columns
        print("Checking all UTN workflow columns (20 total)...")
        columns_query = text("""
            SELECT column_name
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet_decision' 
            AND column_name IN (
                'decision_subtype', 'decision_outcome', 'part_type',
                'esmd_request_status', 'esmd_request_payload', 'esmd_request_payload_history',
                'esmd_attempt_count', 'esmd_last_sent_at', 'esmd_last_error',
                'utn', 'utn_status', 'utn_received_at', 'utn_fail_payload',
                'utn_action_required', 'requires_utn_fix',
                'letter_owner', 'letter_status', 'letter_package', 'letter_medical_docs',
                'letter_generated_at', 'letter_sent_to_integration_at'
            )
            ORDER BY column_name
        """)
        
        columns_result = db.execute(columns_query).fetchall()
        found_columns = [row[0] for row in columns_result]
        expected_count = 20
        found_count = len(found_columns)
        
        print(f"   Found {found_count} out of {expected_count} expected columns")
        print()
        
        if found_count == expected_count:
            print("✅ All UTN workflow columns exist.")
        else:
            print(f"⚠️  Missing {expected_count - found_count} columns:")
            expected_columns = [
                'decision_subtype', 'decision_outcome', 'part_type',
                'esmd_request_status', 'esmd_request_payload', 'esmd_request_payload_history',
                'esmd_attempt_count', 'esmd_last_sent_at', 'esmd_last_error',
                'utn', 'utn_status', 'utn_received_at', 'utn_fail_payload',
                'utn_action_required', 'requires_utn_fix',
                'letter_owner', 'letter_status', 'letter_package', 'letter_medical_docs',
                'letter_generated_at', 'letter_sent_to_integration_at'
            ]
            missing = set(expected_columns) - set(found_columns)
            for col in sorted(missing):
                print(f"   - {col}")
        
        print()
        print("=" * 80)
        
        db.close()
        return column_exists
        
    except Exception as e:
        print(f"ERROR: Failed to check database: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = check_decision_subtype_column()
    sys.exit(0 if success else 1)
