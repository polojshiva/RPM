#!/usr/bin/env python3
"""Check constraints on decision_tracking_id"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Check for unique constraint
    result = conn.execute(text("""
        SELECT constraint_name, constraint_type
        FROM information_schema.table_constraints
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet'
          AND constraint_name LIKE '%decision_tracking_id%'
    """))
    constraints = result.fetchall()
    
    print("Constraints on decision_tracking_id:")
    if constraints:
        for constraint in constraints:
            print(f"  - {constraint[0]} ({constraint[1]})")
    else:
        print("  - No constraints found")
    
    # Check for index
    result = conn.execute(text("""
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'service_ops'
          AND tablename = 'packet'
          AND indexname LIKE '%decision_tracking_id%'
    """))
    indexes = result.fetchall()
    
    print("\nIndexes on decision_tracking_id:")
    if indexes:
        for idx in indexes:
            print(f"  - {idx[0]}")
    else:
        print("  - No indexes found")

