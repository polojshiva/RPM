"""
Test script for Stage 1 migrations
Verifies that migrations can be applied and models work correctly
"""
import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
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

def test_migration_011():
    """Test Migration 011: integration_inbox extensions"""
    print("Testing Migration 011: integration_inbox...")
    engine = create_engine(DATABASE_URL, echo=False)
    inspector = inspect(engine)
    
    checks = []
    
    # Check message_type_id column exists
    if inspector.has_table('integration_inbox', schema='service_ops'):
        columns = {col['name']: col for col in inspector.get_columns('integration_inbox', schema='service_ops')}
        checks.append(('message_type_id column', 'message_type_id' in columns))
        
        # Check unique constraint on message_id
        indexes = inspector.get_indexes('integration_inbox', schema='service_ops')
        has_message_id_unique = any(idx['name'] == 'uq_integration_inbox_message_id' for idx in indexes)
        checks.append(('message_id unique constraint', has_message_id_unique))
        
        # Check old constraint is removed
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM information_schema.table_constraints 
                WHERE table_schema = 'service_ops' 
                AND table_name = 'integration_inbox' 
                AND constraint_name = 'uq_integration_inbox_decision_message'
            """))
            old_constraint_exists = result.scalar() > 0
        checks.append(('old constraint removed', not old_constraint_exists))
    
    return checks

def test_migration_012():
    """Test Migration 012: packet_decision extensions"""
    print("Testing Migration 012: packet_decision...")
    engine = create_engine(DATABASE_URL, echo=False)
    inspector = inspect(engine)
    
    checks = []
    
    if inspector.has_table('packet_decision', schema='service_ops'):
        columns = {col['name']: col for col in inspector.get_columns('packet_decision', schema='service_ops')}
        
        # Check all new columns exist
        required_columns = [
            'decision_subtype', 'decision_outcome', 'part_type',
            'esmd_request_status', 'esmd_request_payload', 'esmd_request_payload_history',
            'esmd_attempt_count', 'esmd_last_sent_at', 'esmd_last_error',
            'utn', 'utn_status', 'utn_received_at', 'utn_fail_payload',
            'utn_action_required', 'requires_utn_fix',
            'letter_owner', 'letter_status', 'letter_package', 'letter_medical_docs',
            'letter_generated_at', 'letter_sent_to_integration_at'
        ]
        
        for col_name in required_columns:
            checks.append((f'{col_name} column', col_name in columns))
        
        # Check indexes exist
        indexes = inspector.get_indexes('packet_decision', schema='service_ops')
        index_names = [idx['name'] for idx in indexes]
        required_indexes = [
            'idx_packet_decision_utn_status',
            'idx_packet_decision_requires_utn_fix',
            'idx_packet_decision_esmd_request_status',
            'idx_packet_decision_letter_status',
            'idx_packet_decision_decision_outcome'
        ]
        
        for idx_name in required_indexes:
            checks.append((f'{idx_name} index', idx_name in index_names))
    
    return checks

def test_migration_013():
    """Test Migration 013: integration_receive_serviceops extensions"""
    print("Testing Migration 013: integration_receive_serviceops...")
    engine = create_engine(DATABASE_URL, echo=False)
    inspector = inspect(engine)
    
    checks = []
    
    if inspector.has_table('integration_receive_serviceops', schema='integration'):
        columns = {col['name']: col for col in inspector.get_columns('integration_receive_serviceops', schema='integration')}
        
        # Check new columns exist
        required_columns = [
            'correlation_id', 'attempt_count', 'resend_of_response_id',
            'payload_hash', 'payload_version'
        ]
        
        for col_name in required_columns:
            checks.append((f'{col_name} column', col_name in columns))
        
        # Check foreign key constraint
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) 
                FROM information_schema.table_constraints 
                WHERE table_schema = 'integration' 
                AND table_name = 'integration_receive_serviceops' 
                AND constraint_name = 'fk_irs_resend_of_response_id'
            """))
            fk_exists = result.scalar() > 0
        checks.append(('resend FK constraint', fk_exists))
        
        # Check indexes
        indexes = inspector.get_indexes('integration_receive_serviceops', schema='integration')
        index_names = [idx['name'] for idx in indexes]
        required_indexes = [
            'idx_irs_correlation_id',
            'idx_irs_resend_of_response_id',
            'idx_irs_attempt_count',
            'idx_irs_decision_attempt'
        ]
        
        for idx_name in required_indexes:
            checks.append((f'{idx_name} index', idx_name in index_names))
    
    return checks

def test_sqlalchemy_model():
    """Test that SQLAlchemy model can access new fields"""
    print("Testing SQLAlchemy model...")
    try:
        from app.models.packet_decision_db import PacketDecisionDB
        
        # Check that new fields are defined
        required_fields = [
            'decision_subtype', 'decision_outcome', 'part_type',
            'esmd_request_status', 'esmd_request_payload', 'esmd_request_payload_history',
            'esmd_attempt_count', 'esmd_last_sent_at', 'esmd_last_error',
            'utn', 'utn_status', 'utn_received_at', 'utn_fail_payload',
            'utn_action_required', 'requires_utn_fix',
            'letter_owner', 'letter_status', 'letter_package', 'letter_medical_docs',
            'letter_generated_at', 'letter_sent_to_integration_at'
        ]
        
        checks = []
        for field_name in required_fields:
            has_field = hasattr(PacketDecisionDB, field_name)
            checks.append((f'PacketDecisionDB.{field_name}', has_field))
        
        return checks
    except Exception as e:
        return [('Model import', False), ('Error', str(e))]

def main():
    """Run all migration tests"""
    print("=" * 80)
    print("Stage 1 Migration Tests")
    print("=" * 80)
    print()
    
    all_checks = []
    
    # Test Migration 011
    checks_011 = test_migration_011()
    all_checks.extend(checks_011)
    print(f"  Migration 011: {sum(1 for _, passed in checks_011 if passed)}/{len(checks_011)} checks passed")
    print()
    
    # Test Migration 012
    checks_012 = test_migration_012()
    all_checks.extend(checks_012)
    print(f"  Migration 012: {sum(1 for _, passed in checks_012 if passed)}/{len(checks_012)} checks passed")
    print()
    
    # Test Migration 013
    checks_013 = test_migration_013()
    all_checks.extend(checks_013)
    print(f"  Migration 013: {sum(1 for _, passed in checks_013 if passed)}/{len(checks_013)} checks passed")
    print()
    
    # Test SQLAlchemy model
    checks_model = test_sqlalchemy_model()
    all_checks.extend(checks_model)
    print(f"  SQLAlchemy Model: {sum(1 for _, passed in checks_model if passed)}/{len(checks_model)} checks passed")
    print()
    
    # Summary
    print("=" * 80)
    print("Summary")
    print("=" * 80)
    
    passed = sum(1 for _, result in all_checks if result)
    total = len(all_checks)
    
    print(f"Total: {passed}/{total} checks passed")
    print()
    
    if passed < total:
        print("Failed checks:")
        for check_name, result in all_checks:
            if not result:
                print(f"  [FAIL] {check_name}")
    else:
        print("✅ All checks passed!")
    
    print()
    print("=" * 80)
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())

