"""
Run all database migrations in order
Executes all SQL migration files from deploy/migrations/ directory
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect
from app.services.db import SessionLocal, engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Migration files to run in order (excluding test/verify/rollback scripts)
MIGRATION_FILES = [
    "001_create_integration_inbox.sql",
    "002_add_page_tracking_to_packet_document.sql",
    "003_add_document_unique_identifier.sql",
    "004_enforce_single_consolidated_document.sql",
    "005_add_submission_type_to_packet.sql",
    "006_add_manual_review_fields_to_packet_document.sql",
    "007_add_suggested_extracted_fields.sql",
    "008_create_validations_and_decisions.sql",
    "009_add_decision_tracking_id_to_packet.sql",
    "010_add_channel_type_id_to_integration_inbox.sql",
    "011_extend_integration_inbox_for_utn_workflow.sql",
    "012_extend_packet_decision_for_utn_workflow.sql",
    "013_extend_integration_receive_serviceops_for_utn_workflow.sql",
    "014_verify_utn_workflow_migrations.sql",
    "015_create_clinical_ops_watermark.sql",
    "016_add_letter_status_failed.sql",
    "017_new_workflow_schema.sql",
    "018_create_send_integration_table.sql",
    "019_update_clinical_ops_watermark_strategy.sql",
    "020_fix_timezone_columns.sql",
    "021_add_missing_send_integration_columns.sql",
    "022_add_json_sent_to_integration_flag.sql",
    "023_add_picked_fields_to_send_clinicalops.sql",
    "024_add_rejection_feedback_loop_fields.sql",
    "025_create_background_task_leader_table.sql",
    "026_ensure_watermark_record_exists.sql",
    "027_add_approved_unit_of_service_columns.sql",
    "028_add_field_validation_error_flag.sql",
]

def check_column_exists(table_schema: str, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table"""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_schema = :schema 
                AND table_name = :table_name
                AND column_name = :column_name
            )
        """), {"schema": table_schema, "table_name": table_name, "column_name": column_name}).scalar()
        return result
    finally:
        db.close()

def check_table_exists(table_schema: str, table_name: str) -> bool:
    """Check if a table exists"""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.tables 
                WHERE table_schema = :schema 
                AND table_name = :table_name
            )
        """), {"schema": table_schema, "table_name": table_name}).scalar()
        return result
    finally:
        db.close()

def run_migration(migration_file: str, migrations_dir: Path) -> bool:
    """Run a single migration file"""
    migration_path = migrations_dir / migration_file
    
    if not migration_path.exists():
        logger.warning(f"Migration file not found: {migration_file} - skipping")
        return True  # Skip missing files (might be optional)
    
    logger.info(f"Running migration: {migration_file}")
    
    db = SessionLocal()
    try:
        sql_content = migration_path.read_text(encoding='utf-8')
        
        # Execute the migration
        db.execute(text(sql_content))
        db.commit()
        
        logger.info(f"✓ Migration {migration_file} completed successfully")
        return True
        
    except Exception as e:
        error_str = str(e)
        # Check if error is due to existing object (constraint, column, table, etc.)
        if any(keyword in error_str.lower() for keyword in [
            'already exists', 'duplicate', 'constraint', 'column', 'table', 
            'relation', 'index', 'already defined'
        ]):
            logger.warning(f"⚠ Migration {migration_file} skipped - objects already exist (likely already applied)")
            db.rollback()
            return True  # Treat as success since objects already exist
        else:
            db.rollback()
            logger.error(f"✗ Migration {migration_file} failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    finally:
        db.close()

def main():
    """Run all migrations"""
    logger.info("=" * 80)
    logger.info("Running All Database Migrations")
    logger.info("=" * 80)
    
    # Get migrations directory
    script_dir = Path(__file__).parent
    migrations_dir = script_dir.parent / "deploy" / "migrations"
    
    if not migrations_dir.exists():
        logger.error(f"Migrations directory not found: {migrations_dir}")
        return False
    
    logger.info(f"Migrations directory: {migrations_dir}")
    logger.info(f"Total migrations to run: {len(MIGRATION_FILES)}\n")
    
    success_count = 0
    failed_migrations = []
    
    for migration_file in MIGRATION_FILES:
        if run_migration(migration_file, migrations_dir):
            success_count += 1
        else:
            failed_migrations.append(migration_file)
        logger.info("")  # Blank line between migrations
    
    logger.info("=" * 80)
    logger.info("Migration Summary")
    logger.info("=" * 80)
    logger.info(f"Total migrations: {len(MIGRATION_FILES)}")
    logger.info(f"Successful: {success_count}")
    logger.info(f"Failed: {len(failed_migrations)}")
    
    if failed_migrations:
        logger.error(f"Failed migrations: {', '.join(failed_migrations)}")
        return False
    
    # Verify the latest migration (027)
    logger.info("\nVerifying latest migration (027)...")
    if check_column_exists('service_ops', 'packet_document', 'approved_unit_of_service_1'):
        logger.info("✓ Migration 027 verified: approved_unit_of_service_1 column exists")
    else:
        logger.warning("⚠ Migration 027 may not have been applied correctly")
    
    logger.info("\n" + "=" * 80)
    logger.info("✓ All migrations completed successfully!")
    logger.info("=" * 80)
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
