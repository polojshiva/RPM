#!/usr/bin/env python3
"""
Script to execute SQL UPDATE statements from a file
Safely executes SQL updates with transaction support and dry-run mode
"""

import sys
import re
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import SessionLocal


def parse_sql_file(file_path):
    """
    Parse SQL file and extract individual UPDATE statements
    Returns list of SQL statements
    """
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Remove comments and split by semicolons
    # Simple approach: split by semicolon and filter empty
    statements = []
    current_statement = []
    
    for line in content.split('\n'):
        # Skip comments
        if line.strip().startswith('--'):
            continue
        # Skip BEGIN/COMMIT
        if line.strip().upper() in ('BEGIN;', 'COMMIT;'):
            continue
        
        current_statement.append(line)
        
        # If line ends with semicolon, we have a complete statement
        if line.strip().endswith(';'):
            stmt = '\n'.join(current_statement).strip()
            if stmt:
                statements.append(stmt)
            current_statement = []
    
    return statements


def execute_updates(sql_file, dry_run=True):
    """
    Execute SQL updates from file
    
    Args:
        sql_file: Path to SQL file
        dry_run: If True, only show what would be executed
    """
    statements = parse_sql_file(sql_file)
    
    print(f"Found {len(statements)} UPDATE statement(s) in {sql_file}")
    print("=" * 60)
    
    if dry_run:
        print("[DRY RUN MODE - No changes will be made]\n")
    
    db = SessionLocal()
    try:
        success_count = 0
        error_count = 0
        
        for i, stmt in enumerate(statements, 1):
            try:
                if dry_run:
                    # Extract decision_tracking_id for display
                    match = re.search(r"decision_tracking_id\s*=\s*'([^']+)'", stmt, re.IGNORECASE)
                    dt_id = match.group(1) if match else "unknown"
                    print(f"[{i}] Would execute UPDATE for decision_tracking_id={dt_id}")
                    continue
                
                # Execute statement
                result = db.execute(text(stmt))
                rows_affected = result.rowcount
                
                if rows_affected > 0:
                    success_count += 1
                    match = re.search(r"decision_tracking_id\s*=\s*'([^']+)'", stmt, re.IGNORECASE)
                    dt_id = match.group(1) if match else "unknown"
                    print(f"✅ [{i}] Updated {rows_affected} row(s) for decision_tracking_id={dt_id}")
                else:
                    error_count += 1
                    match = re.search(r"decision_tracking_id\s*=\s*'([^']+)'", stmt, re.IGNORECASE)
                    dt_id = match.group(1) if match else "unknown"
                    print(f"⚠️  [{i}] No rows updated for decision_tracking_id={dt_id}")
                    
            except Exception as e:
                error_count += 1
                print(f"❌ [{i}] Error: {e}")
        
        if not dry_run:
            db.commit()
            print(f"\n✅ Successfully executed {success_count} update(s)")
            if error_count > 0:
                print(f"⚠️  {error_count} update(s) had errors or affected 0 rows")
        else:
            print(f"\n[DRY RUN] Would execute {len(statements)} update(s)")
            
    except Exception as e:
        db.rollback()
        print(f"❌ Fatal error: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Execute SQL UPDATE statements from file')
    parser.add_argument('sql_file', type=str, help='Path to SQL file with UPDATE statements')
    parser.add_argument('--execute', action='store_true', 
                       help='Actually execute updates (default is dry-run)')
    
    args = parser.parse_args()
    
    if not Path(args.sql_file).exists():
        print(f"❌ File not found: {args.sql_file}")
        sys.exit(1)
    
    execute_updates(args.sql_file, dry_run=not args.execute)
    
    if not args.execute:
        print("\n💡 Run with --execute to actually update records")
