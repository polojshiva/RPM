#!/usr/bin/env python3
"""Check if decision_tracking_id column exists in packet table"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import engine
from sqlalchemy import inspect, text

inspector = inspect(engine)
cols = inspector.get_columns('packet', schema='service_ops')

print("Columns in service_ops.packet:")
print("=" * 60)
for col in cols:
    nullable = "NULL" if col['nullable'] else "NOT NULL"
    print(f"{col['name']:30} {str(col['type']):20} {nullable}")

# Check specifically for decision_tracking_id
decision_tracking_id_exists = any(c['name'] == 'decision_tracking_id' for c in cols)
print("\n" + "=" * 60)
if decision_tracking_id_exists:
    print("✓ decision_tracking_id column EXISTS")
    # Check constraints
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet'
              AND constraint_name LIKE '%decision_tracking_id%'
        """))
        constraints = result.fetchall()
        if constraints:
            print("\nConstraints on decision_tracking_id:")
            for constraint in constraints:
                print(f"  - {constraint[0]} ({constraint[1]})")
        else:
            print("\n⚠ No constraints found on decision_tracking_id")
else:
    print("✗ decision_tracking_id column does NOT exist")

