#!/usr/bin/env python3
"""
Validate migration 009: Check for duplicate decision_tracking_id values
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def validate_migration():
    """Validate migration 009"""
    validation_file = Path(__file__).parent.parent / "deploy" / "migrations" / "009_validate_no_duplicates.sql"
    
    if not validation_file.exists():
        logger.error(f"Validation file not found: {validation_file}")
        return False
    
    logger.info(f"Reading validation file: {validation_file}")
    with open(validation_file, 'r', encoding='utf-8') as f:
        validation_sql = f.read()
    
    try:
        with engine.connect() as conn:
            logger.info("Running validation queries...")
            result = conn.execute(text(validation_sql))
            rows = result.fetchall()
            
            if rows:
                logger.warning(f"⚠ Found {len(rows)} issues:")
                for row in rows:
                    logger.warning(f"  {row}")
                return False
            else:
                logger.info("✓ Validation passed: No duplicate decision_tracking_id values found")
                return True
    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = validate_migration()
    sys.exit(0 if success else 1)

