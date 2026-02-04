"""
Apply Stage 1 migrations to database
Executes SQL migration files in order
"""
import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/wiser_ops")

def apply_migration(migration_file: Path):
    """Apply a single migration file"""
    print(f"Applying {migration_file.name}...")
    
    with open(migration_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # Remove comments that are not SQL (lines starting with -- that are not part of SQL)
    # But keep SQL comments that are part of statements
    # Actually, PostgreSQL handles -- comments fine, so we can execute as-is
    
    engine = create_engine(DATABASE_URL, echo=False)
    
    try:
        with engine.connect() as conn:
            # Execute the migration (it has BEGIN/COMMIT)
            conn.execute(text(sql_content))
            conn.commit()
        print(f"  [OK] {migration_file.name} applied successfully")
        return True
    except Exception as e:
        print(f"  [FAIL] {migration_file.name} failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Apply all Stage 1 migrations"""
    print("=" * 80)
    print("Applying Stage 1 Migrations")
    print("=" * 80)
    print()
    
    migrations_dir = Path(__file__).parent.parent / "deploy" / "migrations"
    
    migration_files = [
        migrations_dir / "011_extend_integration_inbox_for_utn_workflow.sql",
        migrations_dir / "012_extend_packet_decision_for_utn_workflow.sql",
        migrations_dir / "013_extend_integration_receive_serviceops_for_utn_workflow.sql",
    ]
    
    results = []
    for migration_file in migration_files:
        if not migration_file.exists():
            print(f"  [FAIL] Migration file not found: {migration_file}")
            results.append(False)
            continue
        
        success = apply_migration(migration_file)
        results.append(success)
        print()
    
    # Run verification
    verification_file = migrations_dir / "014_verify_utn_workflow_migrations.sql"
    if verification_file.exists():
        print("Running verification...")
        try:
            with open(verification_file, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            
            engine = create_engine(DATABASE_URL, echo=False)
            with engine.connect() as conn:
                result = conn.execute(text(sql_content))
                rows = result.fetchall()
                
                print()
                print("Verification Results:")
                print("-" * 80)
                for row in rows:
                    check_name = row[0]
                    status = row[1]
                    status_symbol = "[PASS]" if status == "PASS" else "[FAIL]"
                    print(f"  {status_symbol} {check_name}")
                print("-" * 80)
                
                passed = sum(1 for row in rows if row[1] == "PASS")
                total = len(rows)
                print(f"Total: {passed}/{total} checks passed")
                print()
        except Exception as e:
            print(f"  [WARN] Verification failed: {e}")
            print()
    
    # Summary
    print("=" * 80)
    print("Summary")
    print("=" * 80)
    
    if all(results):
        print("[SUCCESS] All migrations applied successfully!")
        return 0
    else:
        print("[FAIL] Some migrations failed. Check errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

