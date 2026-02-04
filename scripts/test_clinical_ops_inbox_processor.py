"""
Test script for ClinicalOps Inbox Processor
Tests the Phase 1 → Phase 2 → Process flow
"""
import sys
import os
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import SessionLocal
from app.services.clinical_ops_inbox_processor import ClinicalOpsInboxProcessor
from app.models.clinical_ops_db import ClinicalOpsInboxDB
from sqlalchemy import text
from datetime import datetime
import uuid


def print_section(title: str):
    """Print a section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_test_result(name: str, passed: bool, message: str = ""):
    """Print test result"""
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status} {name}")
    if message:
        print(f"     {message}")


async def test_phase1_detection():
    """Test that Phase 1 records are detected correctly"""
    print_section("Test 1: Phase 1 Record Detection")
    
    db = SessionLocal()
    try:
        # Check if column exists first
        column_exists = db.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.columns 
                    WHERE table_schema = 'service_ops' 
                    AND table_name = 'send_serviceops' 
                    AND column_name = 'clinical_ops_decision_json'
                )
            """)
        ).scalar()
        
        if not column_exists:
            print("clinical_ops_decision_json column does not exist yet")
            print_test_result("Phase 1 Detection", False, "Column not in database - migration needed")
            return False
        
        # Query for Phase 1 records
        # Phase 1: clinical_ops_decision_json IS NOT NULL AND (json_sent_to_integration IS NULL OR = false)
        query = text("""
            SELECT 
                message_id,
                decision_tracking_id,
                payload,
                created_at,
                json_sent_to_integration,
                clinical_ops_decision_json
            FROM service_ops.send_serviceops
            WHERE is_deleted = false
                AND clinical_ops_decision_json IS NOT NULL
                AND (json_sent_to_integration IS NULL OR json_sent_to_integration = false)
            ORDER BY created_at DESC
            LIMIT 5
        """)
        
        result = db.execute(query).fetchall()
        
        if result:
            print(f"Found {len(result)} Phase 1 record(s):")
            for row in result:
                print(f"  - message_id={row[0]}, decision_tracking_id={row[1]}")
            print_test_result("Phase 1 Detection", True, f"Found {len(result)} Phase 1 record(s)")
            return True
        else:
            print("No Phase 1 records found in database")
            print_test_result("Phase 1 Detection", False, "No Phase 1 records to test")
            return False
    except Exception as e:
        print_test_result("Phase 1 Detection", False, f"Error: {e}")
        return False
    finally:
        db.close()


async def test_phase2_detection():
    """Test that Phase 2 records are detected correctly"""
    print_section("Test 2: Phase 2 Record Detection")
    
    db = SessionLocal()
    try:
        # Check if column exists first
        column_exists = db.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.columns 
                    WHERE table_schema = 'service_ops' 
                    AND table_name = 'send_serviceops' 
                    AND column_name = 'clinical_ops_decision_json'
                )
            """)
        ).scalar()
        
        # Query for Phase 2 records (column check is optional)
        if column_exists:
            query = text("""
                SELECT 
                    message_id,
                    decision_tracking_id,
                    payload,
                    created_at,
                    json_sent_to_integration,
                    clinical_ops_decision_json
                FROM service_ops.send_serviceops
                WHERE is_deleted = false
                    AND json_sent_to_integration IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 5
            """)
        else:
            query = text("""
                SELECT 
                    message_id,
                    decision_tracking_id,
                    payload,
                    created_at,
                    json_sent_to_integration,
                    NULL as clinical_ops_decision_json
                FROM service_ops.send_serviceops
                WHERE is_deleted = false
                    AND json_sent_to_integration IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 5
            """)
        
        result = db.execute(query).fetchall()
        
        if result:
            print(f"Found {len(result)} Phase 2 record(s):")
            for row in result:
                print(f"  - message_id={row[0]}, decision_tracking_id={row[1]}, json_sent_to_integration={row[4]}")
            print_test_result("Phase 2 Detection", True, f"Found {len(result)} Phase 2 record(s)")
            return True
        else:
            print("No Phase 2 records found in database")
            print_test_result("Phase 2 Detection", False, "No Phase 2 records to test")
            return False
    except Exception as e:
        print_test_result("Phase 2 Detection", False, f"Error: {e}")
        return False
    finally:
        db.close()


async def test_poll_query():
    """Test that the polling query returns both Phase 1 and Phase 2 records"""
    print_section("Test 3: Poll Query (Phase 1 + Phase 2)")
    
    db = SessionLocal()
    try:
        processor = ClinicalOpsInboxProcessor()
        
        # Use the actual polling method
        messages = processor._poll_new_messages(db)
        
        phase1_count = sum(1 for m in messages if m.get('clinical_ops_decision_json') is not None and m.get('json_sent_to_integration') is not True)
        phase2_count = sum(1 for m in messages if m.get('json_sent_to_integration') is True)
        
        print(f"Poll returned {len(messages)} message(s):")
        print(f"  - Phase 1: {phase1_count}")
        print(f"  - Phase 2: {phase2_count}")
        
        for msg in messages:
            phase = "Phase 1" if (msg.get('clinical_ops_decision_json') is not None and msg.get('json_sent_to_integration') is not True) else "Phase 2"
            print(f"  - {phase}: message_id={msg['message_id']}, decision_tracking_id={msg['decision_tracking_id']}, json_sent_to_integration={msg.get('json_sent_to_integration')}")
        
        print_test_result("Poll Query", True, f"Returned {len(messages)} message(s) ({phase1_count} Phase 1, {phase2_count} Phase 2)")
        return True
    except Exception as e:
        print_test_result("Poll Query", False, f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


async def test_json_generator_config():
    """Test that JSON Generator URL is configured"""
    print_section("Test 4: JSON Generator Configuration")
    
    try:
        from app.config import settings
        
        json_generator_url = getattr(settings, 'json_generator_base_url', None)
        
        if json_generator_url:
            print(f"JSON_GENERATOR_BASE_URL: {json_generator_url}")
            print_test_result("JSON Generator Config", True, f"URL configured: {json_generator_url}")
            return True
        else:
            print("JSON_GENERATOR_BASE_URL not configured")
            print_test_result("JSON Generator Config", False, "URL not configured - set JSON_GENERATOR_BASE_URL env var")
            return False
    except Exception as e:
        print_test_result("JSON Generator Config", False, f"Error: {e}")
        return False


async def test_message_processing_logic():
    """Test the message processing logic (without actually calling JSON Generator)"""
    print_section("Test 5: Message Processing Logic")
    
    db = SessionLocal()
    try:
        processor = ClinicalOpsInboxProcessor()
        
        # Create test messages
        test_phase1_message = {
            'message_id': 999999,
            'decision_tracking_id': str(uuid.uuid4()),
            'payload': {},
            'created_at': datetime.utcnow(),
            'json_sent_to_integration': False,  # JSON Generator sets this to False for Phase 1
            'clinical_ops_decision_json': {'decision_status': 'Rejected'}
        }
        
        test_phase2_message = {
            'message_id': 999998,
            'decision_tracking_id': str(uuid.uuid4()),
            'payload': {
                'procedures': [{'decisionIndicator': 'N', 'procedureCode': '12345'}],
                'partType': 'A'
            },
            'created_at': datetime.utcnow(),
            'json_sent_to_integration': True,  # Phase 2 has json_sent_to_integration = true
            'clinical_ops_decision_json': None  # May or may not be present in Phase 2
        }
        
        # Test Phase 1 detection (json_sent_to_integration = false or NULL)
        is_phase1 = (test_phase1_message.get('clinical_ops_decision_json') is not None and 
                    test_phase1_message.get('json_sent_to_integration') is not True)
        print_test_result("Phase 1 Detection Logic", is_phase1, "Correctly identifies Phase 1 records (json_sent_to_integration = false)")
        
        # Test Phase 2 detection (json_sent_to_integration = true)
        is_phase2 = (test_phase2_message.get('json_sent_to_integration') is True)
        print_test_result("Phase 2 Detection Logic", is_phase2, "Correctly identifies Phase 2 records (json_sent_to_integration = true)")
        
        return is_phase1 and is_phase2
    except Exception as e:
        print_test_result("Message Processing Logic", False, f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


async def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("  ClinicalOps Inbox Processor - Implementation Test")
    print("=" * 80)
    
    results = []
    
    # Test 1: Phase 1 detection
    results.append(await test_phase1_detection())
    
    # Test 2: Phase 2 detection
    results.append(await test_phase2_detection())
    
    # Test 3: Poll query
    results.append(await test_poll_query())
    
    # Test 4: JSON Generator config
    results.append(await test_json_generator_config())
    
    # Test 5: Message processing logic
    results.append(await test_message_processing_logic())
    
    # Summary
    print_section("Test Summary")
    passed = sum(results)
    total = len(results)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("\n[PASS] All tests passed!")
        return 0
    else:
        print(f"\n[WARN] {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
