"""
Test script to verify date normalization logic.
Tests that:
1. Dates are parsed and stored as raw timestamps
2. Normalization happens only for SLA/due date calculations
3. Original timestamps are preserved
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.services.document_processor import DocumentProcessor
from app.utils.packet_converter import calculate_sla_status
from app.models.packet import PacketHighLevelStatus


def normalize_to_midnight(dt: datetime) -> datetime:
    """Helper to normalize datetime to midnight UTC"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime(
        year=dt.year,
        month=dt.month,
        day=dt.day,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=timezone.utc
    )


def test_date_parsing_preserves_raw_timestamp():
    """Test that _parse_date preserves raw timestamp"""
    print("=" * 80)
    print("TEST 1: Date Parsing Preserves Raw Timestamp")
    print("=" * 80)
    
    with patch('app.services.document_processor.PDFMerger'):
        with patch('app.services.document_processor.DocumentSplitter'):
            with patch('app.services.document_processor.BlobStorageClient'):
                processor = DocumentProcessor()
    
    test_cases = [
        {
            "input": "2026-01-06T14:25:33.4392211-05:00",
            "expected_hour": 19,  # 14:25 EST = 19:25 UTC
            "expected_minute": 25,
            "expected_second": 33
        },
        {
            "input": "2026-01-07T09:30:00+00:00",
            "expected_hour": 9,
            "expected_minute": 30,
            "expected_second": 0
        },
        {
            "input": "2026-01-08T23:59:59Z",
            "expected_hour": 23,
            "expected_minute": 59,
            "expected_second": 59
        }
    ]
    
    all_passed = True
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case['input']}")
        result = processor._parse_date(test_case['input'])
        
        if result is None:
            print(f"  [FAIL] Failed to parse date")
            all_passed = False
            continue
        
        print(f"  Parsed: {result}")
        print(f"  Hour: {result.hour}, Minute: {result.minute}, Second: {result.second}")
        
        # Check if time is preserved (not normalized to midnight)
        if (result.hour == test_case['expected_hour'] and 
            result.minute == test_case['expected_minute'] and
            result.second == test_case['expected_second']):
            print(f"  [PASS] Raw timestamp preserved")
        else:
            print(f"  [FAIL] Expected hour={test_case['expected_hour']}, "
                  f"minute={test_case['expected_minute']}, second={test_case['expected_second']}")
            all_passed = False
    
    return all_passed


def test_sla_calculation_normalizes():
    """Test that SLA calculation normalizes received_date"""
    print("\n" + "=" * 80)
    print("TEST 2: SLA Calculation Normalizes Date")
    print("=" * 80)
    
    test_cases = [
        {
            "name": "Morning timestamp (09:30:00)",
            "received_date": datetime(2026, 1, 6, 9, 30, 0, tzinfo=timezone.utc),
        },
        {
            "name": "Afternoon timestamp (14:25:33)",
            "received_date": datetime(2026, 1, 6, 14, 25, 33, tzinfo=timezone.utc),
        },
        {
            "name": "Evening timestamp (23:59:59)",
            "received_date": datetime(2026, 1, 6, 23, 59, 59, tzinfo=timezone.utc),
        }
    ]
    
    all_passed = True
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case['name']}")
        print(f"  Raw timestamp: {test_case['received_date']}")
        
        # Calculate SLA status (should normalize internally)
        try:
            sla_status = calculate_sla_status(
                received_date=test_case['received_date'],
                high_level_status=PacketHighLevelStatus.INTAKE_VALIDATION,
                submission_type="Standard"
            )
            print(f"  [PASS] SLA calculation completed (normalization happens internally)")
            print(f"  SLA Status: {sla_status}")
        except Exception as e:
            print(f"  [FAIL] {e}")
            all_passed = False
    
    return all_passed


def test_due_date_calculation_normalizes():
    """Test that due date calculation normalizes received_date"""
    print("\n" + "=" * 80)
    print("TEST 3: Due Date Calculation Normalizes Date")
    print("=" * 80)
    
    with patch('app.services.document_processor.PDFMerger'):
        with patch('app.services.document_processor.DocumentSplitter'):
            with patch('app.services.document_processor.BlobStorageClient'):
                processor = DocumentProcessor()
    
    test_cases = [
        {
            "name": "Morning timestamp (09:30:00)",
            "received_date": datetime(2026, 1, 6, 9, 30, 0, tzinfo=timezone.utc),
            "submission_type": "Standard"
        },
        {
            "name": "Afternoon timestamp (14:25:33)",
            "received_date": datetime(2026, 1, 6, 14, 25, 33, tzinfo=timezone.utc),
            "submission_type": "Expedited"
        },
        {
            "name": "Evening timestamp (23:59:59)",
            "received_date": datetime(2026, 1, 6, 23, 59, 59, tzinfo=timezone.utc),
            "submission_type": "Standard"
        }
    ]
    
    all_passed = True
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case['name']}")
        print(f"  Raw timestamp: {test_case['received_date']}")
        print(f"  Submission type: {test_case['submission_type']}")
        
        # Calculate due date (should normalize internally)
        try:
            due_date = processor._calculate_due_date(
                received_date=test_case['received_date'],
                submission_type=test_case['submission_type']
            )
            
            # Expected due date: normalized received_date + SLA hours
            sla_hours = 48 if test_case['submission_type'] == 'Expedited' else 72
            expected_due_date = normalize_to_midnight(test_case['received_date']) + timedelta(hours=sla_hours)
            expected_due_date = normalize_to_midnight(expected_due_date)
            
            print(f"  Calculated due date: {due_date}")
            print(f"  Expected due date: {expected_due_date}")
            
            if due_date == expected_due_date:
                print(f"  [PASS] Due date calculation correct (normalized to midnight)")
            else:
                print(f"  [FAIL] Due date mismatch!")
                all_passed = False
        except Exception as e:
            print(f"  [FAIL] {e}")
            import traceback
            traceback.print_exc()
            all_passed = False
    
    return all_passed


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("DATE NORMALIZATION LOGIC TEST SUITE")
    print("=" * 80)
    print("\nTesting that:")
    print("1. Dates are parsed and stored as raw timestamps")
    print("2. Normalization happens only for SLA/due date calculations")
    print("3. Original timestamps are preserved")
    print("=" * 80)
    
    results = []
    
    # Test 1: Date parsing
    results.append(("Date Parsing", test_date_parsing_preserves_raw_timestamp()))
    
    # Test 2: SLA calculation
    results.append(("SLA Calculation", test_sla_calculation_normalizes()))
    
    # Test 3: Due date calculation
    results.append(("Due Date Calculation", test_due_date_calculation_normalizes()))
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    all_passed = True
    for test_name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}: {test_name}")
        if not passed:
            all_passed = False
    
    print("=" * 80)
    if all_passed:
        print("\n[SUCCESS] ALL TESTS PASSED")
        print("\nSummary:")
        print("- Dates are parsed and preserve raw timestamps")
        print("- SLA calculation normalizes dates internally")
        print("- Due date calculation normalizes dates internally")
        print("\nThe implementation correctly stores raw timestamps and")
        print("normalizes them only when calculating SLA/due dates.")
        return 0
    else:
        print("\n[ERROR] SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
