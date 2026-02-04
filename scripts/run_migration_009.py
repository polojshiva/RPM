#!/usr/bin/env python3
"""
Run migration 009: Add decision_tracking_id to packet table
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import engine, get_db_session
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """Run migration 009"""
    migration_file = Path(__file__).parent.parent / "deploy" / "migrations" / "009_add_decision_tracking_id_to_packet.sql"
    
    if not migration_file.exists():
        logger.error(f"Migration file not found: {migration_file}")
        return False
    
    logger.info(f"Reading migration file: {migration_file}")
    with open(migration_file, 'r', encoding='utf-8') as f:
        migration_sql = f.read()
    
    try:
        with engine.connect() as conn:
            # Execute migration in a transaction
            logger.info("Starting migration 009...")
            conn.execute(text(migration_sql))
            conn.commit()
            logger.info("✓ Migration 009 completed successfully")
            return True
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)

