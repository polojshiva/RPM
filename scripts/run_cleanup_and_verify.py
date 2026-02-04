"""
Run database cleanup script and verify all tables are clean
Preserves only message_id, decision_tracking_id, and payload in integration.send_serviceops
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

def run_cleanup():
    """Run the cleanup SQL script"""
    print("=" * 80)
    print("Running Database Cleanup Script")
    print("=" * 80)
    
    cleanup_script_path = Path(__file__).parent / "clean_db_for_testing.sql"
    
    if not cleanup_script_path.exists():
        print(f"ERROR: Cleanup script not found at {cleanup_script_path}")
        return False
    
    with open(cleanup_script_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    engine = create_engine(DATABASE_URL, echo=False)
    
    try:
        with engine.connect() as conn:
            # Execute the cleanup script (it has BEGIN/COMMIT)
            conn.execute(text(sql_content))
            conn.commit()
        print("✓ Cleanup script executed successfully")
        return True
    except Exception as e:
        print(f"✗ Cleanup script failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_cleanup():
    """Verify that all tables are clean and send_serviceops has preserved data"""
    print("\n" + "=" * 80)
    print("Verifying Cleanup Results")
    print("=" * 80)
    
    engine = create_engine(DATABASE_URL, echo=False)
    
    try:
        with engine.connect() as conn:
            # Check row counts for all tables
            tables_to_check = [
                ("service_ops.packet", "Should be 0"),
                ("service_ops.packet_document", "Should be 0"),
                ("service_ops.packet_decision", "Should be 0"),
                ("service_ops.packet_validation", "Should be 0"),
                ("service_ops.integration_inbox", "Should be 0"),
                ("service_ops.send_integration", "Should be 0"),
                ("integration.send_serviceops", "Should have preserved rows"),
            ]
            
            print("\n📊 Table Row Counts:")
            print("-" * 80)
            
            all_clean = True
            send_serviceops_count = 0
            
            for table_name, expected in tables_to_check:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = result.scalar()
                
                status = "✓" if (count == 0 and "Should be 0" in expected) or (count > 0 and "preserved" in expected) else "✗"
                
                print(f"{status} {table_name:50} {count:6} rows  ({expected})")
                
                if table_name == "integration.send_serviceops":
                    send_serviceops_count = count
                elif count > 0:
                    all_clean = False
            
            # Verify send_serviceops has the three key fields
            print("\n📋 Verifying send_serviceops preserved fields:")
            print("-" * 80)
            
            if send_serviceops_count > 0:
                result = conn.execute(text("""
                    SELECT 
                        COUNT(*) as total_rows,
                        COUNT(message_id) as has_message_id,
                        COUNT(decision_tracking_id) as has_decision_tracking_id,
                        COUNT(payload) as has_payload
                    FROM integration.send_serviceops
                    WHERE is_deleted = false
                """))
                row = result.fetchone()
                
                total = row[0]
                has_message_id = row[1]
                has_decision_tracking_id = row[2]
                has_payload = row[3]
                
                print(f"  Total rows: {total}")
                print(f"  ✓ message_id present: {has_message_id}/{total}")
                print(f"  ✓ decision_tracking_id present: {has_decision_tracking_id}/{total}")
                print(f"  ✓ payload present: {has_payload}/{total}")
                
                if has_message_id == total and has_decision_tracking_id == total and has_payload == total:
                    print("  ✓ All three key fields are preserved!")
                else:
                    print("  ✗ Some key fields are missing!")
                    all_clean = False
            else:
                print("  ⚠ No rows found in send_serviceops (this is OK if you want to start completely fresh)")
            
            # Check watermark reset
            print("\n🔄 Verifying watermark reset:")
            print("-" * 80)
            
            result = conn.execute(text("""
                SELECT last_created_at, last_message_id
                FROM service_ops.integration_poll_watermark
                WHERE id = 1
            """))
            watermark = result.fetchone()
            
            if watermark:
                last_created_at = watermark[0]
                last_message_id = watermark[1]
                print(f"  last_created_at: {last_created_at}")
                print(f"  last_message_id: {last_message_id}")
                
                if str(last_created_at) == "1970-01-01 00:00:00" and last_message_id == 0:
                    print("  ✓ Watermark reset successfully")
                else:
                    print("  ✗ Watermark not reset properly")
                    all_clean = False
            else:
                print("  ✗ Watermark row not found")
                all_clean = False
            
            # Summary
            print("\n" + "=" * 80)
            if all_clean and send_serviceops_count > 0:
                print("✅ VERIFICATION PASSED: All tables cleaned, send_serviceops preserved")
            elif all_clean and send_serviceops_count == 0:
                print("✅ VERIFICATION PASSED: All tables cleaned (send_serviceops was empty)")
            else:
                print("❌ VERIFICATION FAILED: Some issues found")
            print("=" * 80)
            
            return all_clean
            
    except Exception as e:
        print(f"✗ Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    print("\n" + "=" * 80)
    print("Database Cleanup and Verification")
    print("=" * 80)
    print(f"Database URL: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'Not set'}")
    print()
    
    # Run cleanup
    if not run_cleanup():
        print("\n❌ Cleanup failed. Aborting verification.")
        sys.exit(1)
    
    # Verify cleanup
    if not verify_cleanup():
        print("\n❌ Verification failed. Please check the results above.")
        sys.exit(1)
    
    print("\n✅ All done! Database is clean and ready for testing.")
    print()

if __name__ == "__main__":
    main()

