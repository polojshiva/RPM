#!/usr/bin/env python3
"""
Run migration 030: Add clinical_decision_applied_at column to send_serviceops

This migration adds a column to track when clinical decisions have been successfully
applied to packet_decision, enabling reliable retry logic and preventing watermark
from skipping failed messages.

Usage:
    python scripts/run_migration_030.py
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import get_db_connection
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Execute migration 030 SQL script"""
    migration_file = Path(__file__).parent.parent / "deploy" / "migrations" / "030_add_clinical_decision_applied_at.sql"
    
    if not migration_file.exists():
        logger.error(f"Migration file not found: {migration_file}")
        return False
    
    logger.info(f"Reading migration file: {migration_file}")
    with open(migration_file, 'r', encoding='utf-8') as f:
        migration_sql = f.read()
    
    logger.info("Connecting to database...")
    conn = get_db_connection()
    
    try:
        logger.info("Executing migration 030...")
        with conn.begin():
            conn.execute(text(migration_sql))
        
        logger.info("✅ Migration 030 completed successfully!")
        logger.info("Column clinical_decision_applied_at has been added to service_ops.send_serviceops")
        logger.info("Existing Phase 2 rows (json_sent_to_integration=true) have been backfilled with created_at")
        logger.info("Phase 1 rows remain NULL and will be processed by the poller")
        return True
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}", exc_info=True)
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
