"""
Script to run migration scripts for timezone fixes and watermark strategy updates
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text

def run_migration_file(db, migration_file):
    """Run a migration SQL file"""
    migration_path = Path(__file__).parent.parent / "deploy" / "migrations" / migration_file
    
    if not migration_path.exists():
        print(f"[ERROR] Migration file not found: {migration_path}")
        return False
    
    print(f"[INFO] Running migration: {migration_file}")
    
    try:
        sql_content = migration_path.read_text()
        # Execute entire file as one statement (handles DO blocks, BEGIN/COMMIT, etc.)
        # Remove comments and empty lines for cleaner execution
        lines = []
        in_comment = False
        for line in sql_content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('--'):
                continue  # Skip comment lines
            if not stripped:
                continue  # Skip empty lines
            lines.append(line)
        
        # Join and execute as single statement
        full_sql = '\n'.join(lines)
        db.execute(text(full_sql))
        db.commit()
        print(f"[OK] Migration {migration_file} completed successfully")
        return True
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Migration {migration_file} failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all migration scripts"""
    db = SessionLocal()
    try:
        migrations = [
            "019_update_clinical_ops_watermark_strategy.sql",
            "020_fix_timezone_columns.sql",
            "021_add_missing_send_integration_columns.sql"
        ]
        
        print("[INFO] Starting migration scripts...")
        print()
        
        for migration in migrations:
            success = run_migration_file(db, migration)
            if not success:
                print(f"[ERROR] Failed to run {migration}. Stopping.")
                return
            print()
        
        print("[OK] All migrations completed successfully!")
        print()
        print("[INFO] Verifying changes...")
        
        # Verify clinical_ops_poll_watermark
        result1 = db.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'clinical_ops_poll_watermark' 
            AND column_name = 'last_created_at'
        """)).fetchone()
        
        if result1:
            print(f"  clinical_ops_poll_watermark.last_created_at: {result1[1]}")
        
        # Verify send_serviceops.created_at
        result2 = db.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'send_serviceops' 
            AND column_name = 'created_at'
        """)).fetchone()
        
        if result2:
            print(f"  send_serviceops.created_at: {result2[1]}")
        
        # Verify integration_poll_watermark
        result3 = db.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'integration_poll_watermark' 
            AND column_name = 'last_created_at'
        """)).fetchone()
        
        if result3:
            print(f"  integration_poll_watermark.last_created_at: {result3[1]}")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error during migration: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

