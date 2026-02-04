"""
Run migration 029: Add clinical_ops_decision_json column
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.services.db import SessionLocal

def run_migration():
    """Run migration 029"""
    db = SessionLocal()
    try:
        print("Running migration 029: Add clinical_ops_decision_json column")
        print("=" * 80)
        
        # Check if column already exists
        column_exists = db.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.columns 
                    WHERE table_schema = 'service_ops' 
                    AND table_name = 'send_serviceops' 
                    AND column_name = 'clinical_ops_decision_json'
                )
            """)
        ).scalar()
        
        if column_exists:
            print("[INFO] Column already exists, skipping migration")
            return True
        
        # Run migration
        print("Adding column...")
        db.execute(
            text("ALTER TABLE service_ops.send_serviceops ADD COLUMN IF NOT EXISTS clinical_ops_decision_json JSONB")
        )
        
        print("Adding comment...")
        db.execute(
            text("""
                COMMENT ON COLUMN service_ops.send_serviceops.clinical_ops_decision_json IS 
                    'Phase 1: Clinical decision data from Clinical Ops (written by JSON Generator). Contains decision_indicator (A/N), claim_id, decision_status, etc. NULL = not a Phase 1 record.'
            """)
        )
        
        print("Creating index...")
        db.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_send_serviceops_clinical_decision 
                ON service_ops.send_serviceops(decision_tracking_id, clinical_ops_decision_json)
                WHERE clinical_ops_decision_json IS NOT NULL
            """)
        )
        
        db.commit()
        print()
        print("[SUCCESS] Migration completed successfully")
        return True
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
