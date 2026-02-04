#!/usr/bin/env python3
"""
Simple script to execute UPDATE statements for integration.send_serviceops
Usage: 
    python execute_updates.py < updates.sql
    OR
    python execute_updates.py --file updates.sql --execute
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import SessionLocal


def execute_sql(sql_content, dry_run=True):
    """Execute SQL content"""
    # Split by semicolon, but keep UPDATE statements together
    statements = []
    current = []
    
    for line in sql_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('--'):
            continue
        current.append(line)
        if line.endswith(';'):
            stmt = ' '.join(current)
            if stmt.upper().startswith('UPDATE'):
                statements.append(stmt)
            current = []
    
    print(f"Found {len(statements)} UPDATE statement(s)")
    if dry_run:
        print("[DRY RUN - No changes will be made]\n")
    
    db = SessionLocal()
    try:
        success = 0
        errors = 0
        
        for i, stmt in enumerate(statements, 1):
            try:
                # Extract decision_tracking_id for logging
                match = re.search(r"decision_tracking_id\s*=\s*'([^']+)'", stmt, re.I)
                dt_id = match.group(1) if match else f"update_{i}"
                
                if dry_run:
                    print(f"[{i}] Would update: {dt_id}")
                    continue
                
                result = db.execute(text(stmt))
                if result.rowcount > 0:
                    success += 1
                    print(f"✅ [{i}] Updated {result.rowcount} row(s): {dt_id}")
                else:
                    errors += 1
                    print(f"⚠️  [{i}] No rows updated: {dt_id}")
            except Exception as e:
                errors += 1
                print(f"❌ [{i}] Error: {e}")
        
        if not dry_run:
            db.commit()
            print(f"\n✅ Success: {success}, Errors/Not found: {errors}")
        else:
            print(f"\n[DRY RUN] Would execute {len(statements)} updates")
    except Exception as e:
        db.rollback()
        print(f"❌ Fatal: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', help='SQL file path')
    parser.add_argument('--execute', action='store_true', help='Actually execute (default: dry-run)')
    args = parser.parse_args()
    
    if args.file:
        sql = Path(args.file).read_text()
    else:
        sql = sys.stdin.read()
    
    execute_sql(sql, dry_run=not args.execute)
