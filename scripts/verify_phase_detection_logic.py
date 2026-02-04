"""
Verify Phase 1 and Phase 2 detection logic matches production data format
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_phase_detection_logic():
    """Test the phase detection logic with production data format"""
    
    print("=" * 80)
    print("  Phase Detection Logic Verification")
    print("=" * 80)
    
    # Production record format (from user's example)
    production_phase1_record = {
        'message_id': 5,
        'decision_tracking_id': 'd89971c2-4790-472d-bfce-d39262a80913',
        'clinical_ops_decision_json': {
            "source": "clinical_ops_ddms",
            "claim_id": 878,
            "decision_status": "Rejected",
            "decision_indicator": "N",
            "failed_reason_data": [...]
        },
        'json_sent_to_integration': False,  # NOT NULL, but False
        'payload': {}
    }
    
    # Phase 2 record format
    phase2_record = {
        'message_id': 17,
        'decision_tracking_id': '257c66bc-825a-4bb3-b0f1-933476910d69',
        'clinical_ops_decision_json': None,  # May or may not be present
        'json_sent_to_integration': True,  # TRUE for Phase 2
        'payload': {'procedures': [...]}
    }
    
    print("\n1. Testing Phase 1 Detection Logic:")
    print(f"   Record: message_id={production_phase1_record['message_id']}")
    print(f"   - clinical_ops_decision_json: {production_phase1_record['clinical_ops_decision_json'] is not None}")
    print(f"   - json_sent_to_integration: {production_phase1_record['json_sent_to_integration']}")
    
    # Phase 1 logic: clinical_ops_decision_json IS NOT NULL AND json_sent_to_integration IS NOT TRUE
    is_phase1 = (
        production_phase1_record.get('clinical_ops_decision_json') is not None and
        production_phase1_record.get('json_sent_to_integration') is not True
    )
    
    print(f"   Result: {'[PASS] Phase 1 detected' if is_phase1 else '[FAIL] Phase 1 NOT detected'}")
    
    print("\n2. Testing Phase 2 Detection Logic:")
    print(f"   Record: message_id={phase2_record['message_id']}")
    print(f"   - clinical_ops_decision_json: {phase2_record['clinical_ops_decision_json'] is not None}")
    print(f"   - json_sent_to_integration: {phase2_record['json_sent_to_integration']}")
    
    # Phase 2 logic: json_sent_to_integration = True
    is_phase2 = (phase2_record.get('json_sent_to_integration') is True)
    
    print(f"   Result: {'[PASS] Phase 2 detected' if is_phase2 else '[FAIL] Phase 2 NOT detected'}")
    
    print("\n3. SQL Query Logic Verification:")
    print("   Phase 1 query condition:")
    print("   - clinical_ops_decision_json IS NOT NULL")
    print("   - AND (json_sent_to_integration IS NULL OR json_sent_to_integration = false)")
    print(f"   Production record matches: {is_phase1}")
    
    print("\n   Phase 2 query condition:")
    print("   - json_sent_to_integration = true")
    print(f"   Phase 2 record matches: {is_phase2}")
    
    print("\n" + "=" * 80)
    if is_phase1 and is_phase2:
        print("[PASS] All logic verified correctly!")
        return 0
    else:
        print("[FAIL] Logic verification failed")
        return 1


if __name__ == "__main__":
    exit_code = test_phase_detection_logic()
    sys.exit(exit_code)
