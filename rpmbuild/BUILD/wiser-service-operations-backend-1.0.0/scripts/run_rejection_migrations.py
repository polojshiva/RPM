"""
Run migrations for ClinicalOps rejection feedback loop
Runs migrations 023 and 024 to add is_picked, error_reason, is_looped_back_to_validation, and retry_count columns
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Try to load from .env file
from dotenv import load_dotenv
load_dotenv()

# Get database URL
database_url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
if not database_url:
    print("ERROR: DATABASE_URL or POSTGRES_URL environment variable not set")
    print("Please set DATABASE_URL in your .env file or environment")
    sys.exit(1)

# Create database connection
engine = create_engine(database_url)
Session = sessionmaker(bind=engine)
db = Session()

def check_column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table"""
    result = db.execute(text("""
        SELECT EXISTS (
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = :table_name
            AND column_name = :column_name
        )
    """), {"table_name": table_name, "column_name": column_name}).scalar()
    return result

def run_migration_023():
    """Run migration 023: Add is_picked and error_reason"""
    print("\n" + "=" * 80)
    print("Migration 023: Add is_picked and error_reason columns")
    print("=" * 80)
    
    # Check if columns already exist
    if check_column_exists("send_clinicalops", "is_picked"):
        print("[SKIP] Column is_picked already exists")
    else:
        print("[RUN] Adding is_picked column...")
        db.execute(text("""
            ALTER TABLE service_ops.send_clinicalops
            ADD COLUMN IF NOT EXISTS is_picked BOOLEAN DEFAULT NULL;
        """))
        db.execute(text("""
            COMMENT ON COLUMN service_ops.send_clinicalops.is_picked IS 
                'Indicates if ClinicalOps has reviewed this record. NULL = not yet reviewed, TRUE = picked and processed successfully, FALSE = picked but has errors (check error_reason).';
        """))
        print("[OK] Added is_picked column")
    
    if check_column_exists("send_clinicalops", "error_reason"):
        print("[SKIP] Column error_reason already exists")
    else:
        print("[RUN] Adding error_reason column...")
        db.execute(text("""
            ALTER TABLE service_ops.send_clinicalops
            ADD COLUMN IF NOT EXISTS error_reason VARCHAR(500) DEFAULT NULL;
        """))
        db.execute(text("""
            COMMENT ON COLUMN service_ops.send_clinicalops.error_reason IS 
                'Reason why the record was rejected by ClinicalOps (e.g., "Missing HCPCS code", "Invalid provider NPI"). Only populated when is_picked = FALSE.';
        """))
        print("[OK] Added error_reason column")
    
    # Create index
    print("[RUN] Creating index for is_picked...")
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_send_clinicalops_is_picked 
        ON service_ops.send_clinicalops(is_picked)
        WHERE is_picked IS NULL;
    """))
    print("[OK] Created index")
    
    db.commit()
    print("[OK] Migration 023 complete!")

def run_migration_024():
    """Run migration 024: Add is_looped_back_to_validation and retry_count"""
    print("\n" + "=" * 80)
    print("Migration 024: Add rejection feedback loop fields")
    print("=" * 80)
    
    # Check if columns already exist
    if check_column_exists("send_clinicalops", "is_looped_back_to_validation"):
        print("[SKIP] Column is_looped_back_to_validation already exists")
    else:
        print("[RUN] Adding is_looped_back_to_validation column...")
        db.execute(text("""
            ALTER TABLE service_ops.send_clinicalops
            ADD COLUMN IF NOT EXISTS is_looped_back_to_validation BOOLEAN DEFAULT FALSE;
        """))
        db.execute(text("""
            COMMENT ON COLUMN service_ops.send_clinicalops.is_looped_back_to_validation IS 
                'Indicates if a rejected record (is_picked = false) has been looped back to ServiceOps validation phase. Prevents reprocessing.';
        """))
        print("[OK] Added is_looped_back_to_validation column")
    
    if check_column_exists("send_clinicalops", "retry_count"):
        print("[SKIP] Column retry_count already exists")
    else:
        print("[RUN] Adding retry_count column...")
        db.execute(text("""
            ALTER TABLE service_ops.send_clinicalops
            ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;
        """))
        db.execute(text("""
            COMMENT ON COLUMN service_ops.send_clinicalops.retry_count IS 
                'Number of times this decision_tracking_id has been sent to ClinicalOps. Prevents infinite retry loops.';
        """))
        print("[OK] Added retry_count column")
    
    # Create index
    print("[RUN] Creating index for rejected unprocessed records...")
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_send_clinicalops_rejected_unprocessed 
        ON service_ops.send_clinicalops(is_picked, is_looped_back_to_validation)
        WHERE is_picked = FALSE AND is_looped_back_to_validation = FALSE;
    """))
    print("[OK] Created index")
    
    db.commit()
    print("[OK] Migration 024 complete!")

def main():
    print("=" * 80)
    print("ClinicalOps Rejection Feedback Loop - Migration Runner")
    print("=" * 80)
    
    try:
        # Run migrations
        run_migration_023()
        run_migration_024()
        
        print("\n" + "=" * 80)
        print("[OK] All migrations complete!")
        print("=" * 80)
        print("\nYou can now run the test script:")
        print("  python scripts/test_clinical_ops_rejection_workflow.py --process")
        
    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
