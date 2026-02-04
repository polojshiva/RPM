"""Check what columns exist in service_ops.packet table"""
from app.services.db import SessionLocal
from sqlalchemy import inspect, text

db = SessionLocal()
try:
    # Get column info
    inspector = inspect(db.bind)
    cols = inspector.get_columns('packet', schema='service_ops')
    
    print("=" * 60)
    print("Columns in service_ops.packet table:")
    print("=" * 60)
    for col in cols:
        print(f"  {col['name']:30} {str(col['type'])}")
    
    print("\n" + "=" * 60)
    print("Analysis for Step 5:")
    print("=" * 60)
    
    # Check if we have columns we can use
    col_names = [c['name'] for c in cols]
    
    if 'case_id' in col_names:
        print("✓ case_id column exists - Can store decision_tracking_id (UUID, 36 chars)")
        print("  Note: case_id is String(50), UUID fits perfectly")
    
    if 'external_id' in col_names:
        print("✓ external_id column exists - Can store unique_id or use for display ID")
    
    # Check if we need to add decision_tracking_id
    if 'decision_tracking_id' not in col_names:
        print("\n⚠ decision_tracking_id column does NOT exist")
        print("  Options:")
        print("    1. Use case_id to store decision_tracking_id (recommended)")
        print("    2. Add new decision_tracking_id column (requires DB migration)")
        print("    3. Add JSONB metadata column for tracking info")
    
    print("\n" + "=" * 60)
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()

