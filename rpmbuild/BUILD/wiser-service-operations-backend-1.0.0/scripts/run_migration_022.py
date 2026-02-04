"""
Quick script to run migration 022: Add json_sent_to_integration flag
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text

def main():
    """Run migration 022"""
    db = SessionLocal()
    try:
        migration_file = "022_add_json_sent_to_integration_flag.sql"
        migration_path = Path(__file__).parent.parent / "deploy" / "migrations" / migration_file
        
        if not migration_path.exists():
            print(f"[ERROR] Migration file not found: {migration_path}")
            return False
        
        print(f"[INFO] Running migration: {migration_file}")
        
        sql_content = migration_path.read_text()
        db.execute(text(sql_content))
        db.commit()
        
        print(f"[OK] Migration {migration_file} completed successfully")
        
        # Verify the column was added
        result = db.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'send_serviceops' 
            AND column_name = 'json_sent_to_integration'
        """)).fetchone()
        
        if result:
            print(f"[OK] Verification: Column 'json_sent_to_integration' exists")
            print(f"     Type: {result[1]}, Nullable: {result[2]}")
        else:
            print("[WARNING] Column not found after migration")
        
        return True
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)



