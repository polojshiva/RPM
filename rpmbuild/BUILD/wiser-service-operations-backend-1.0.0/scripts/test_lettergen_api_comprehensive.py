"""
Comprehensive Letter Generation API Testing Script
Tests all endpoints of the LetterGen API at https://dev-wiser-letter-generatorv2.azurewebsites.net

Tests:
1. Health & Version endpoints
2. V2 Letter Generation (affirmation, non-affirmation, dismissal)
3. Batch Processing
4. Recovery & Reprocessing
5. Metadata endpoints
6. Error handling
7. Edge cases
"""

import sys
import os
import json
import httpx
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Base URL for LetterGen API
BASE_URL = "https://dev-wiser-letter-generatorv2.azurewebsites.net"

# Test results tracking
test_results = {
    "passed": [],
    "failed": [],
    "warnings": []
}

def log_test(name: str, passed: bool, message: str = "", warning: bool = False):
    """Log test result"""
    if warning:
        test_results["warnings"].append({"test": name, "message": message})
        print(f"[WARNING] {name} - {message}")
    elif passed:
        test_results["passed"].append({"test": name, "message": message})
        print(f"[PASS] {name} - {message}")
    else:
        test_results["failed"].append({"test": name, "message": message})
        print(f"[FAIL] {name} - {message}")

def make_request(method: str, endpoint: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> tuple[Optional[Dict], Optional[int], Optional[str]]:
    """Make HTTP request to API"""
    url = f"{BASE_URL}{endpoint}"
    try:
        with httpx.Client(timeout=30.0) as client:
            if method == "GET":
                response = client.get(url, params=params)
            elif method == "POST":
                response = client.post(url, json=payload)
            elif method == "PATCH":
                response = client.patch(url, json=payload)
            else:
                return None, None, f"Unsupported method: {method}"
            
            try:
                return response.json(), response.status_code, None
            except:
                return {"text": response.text}, response.status_code, None
    except httpx.TimeoutException as e:
        return None, None, f"Timeout: {str(e)}"
    except httpx.RequestError as e:
        return None, None, f"Request error: {str(e)}"
    except Exception as e:
        return None, None, f"Unexpected error: {str(e)}"

# ============================================================================
# Test Suite 1: Health & Version Endpoints
# ============================================================================

def test_health_check():
    """Test /health endpoint"""
    data, status, error = make_request("GET", "/health")
    if error:
        log_test("Health Check", False, error)
        return
    
    if status == 200:
        log_test("Health Check", True, f"Status: {status}, Response: {data}")
    else:
        log_test("Health Check", False, f"Unexpected status: {status}")

def test_version():
    """Test /version endpoint"""
    data, status, error = make_request("GET", "/version")
    if error:
        log_test("Version Check", False, error)
        return
    
    if status == 200:
        log_test("Version Check", True, f"Version: {data.get('version', 'unknown')}")
    else:
        log_test("Version Check", False, f"Unexpected status: {status}")

def test_build_info():
    """Test /build-info endpoint"""
    data, status, error = make_request("GET", "/build-info")
    if error:
        log_test("Build Info", False, error)
        return
    
    if status == 200:
        build_info = data.get('build_number', 'unknown')
        log_test("Build Info", True, f"Build: {build_info}")
    else:
        log_test("Build Info", False, f"Unexpected status: {status}")

# ============================================================================
# Test Suite 2: V2 Letter Generation Endpoints
# ============================================================================

def create_base_letter_payload(channel: str = "mail", fax_number: Optional[str] = None) -> Dict[str, Any]:
    """Create base letter payload"""
    payload = {
        "patient_name": "John Doe",
        "patient_id": "1S2A3B4C5D6E7F8G9H",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "provider_name": "UPMC Jameson",
        "channel": channel
    }
    if fax_number:
        payload["fax_number"] = fax_number
    return payload

def test_v2_affirmation_mail():
    """Test /api/v2/affirmation with mail channel"""
    payload = create_base_letter_payload(channel="mail")
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("V2 Affirmation (Mail)", False, error)
        return
    
    if status == 200:
        blob_url = data.get('blob_url', 'N/A')
        filename = data.get('filename', 'N/A')
        log_test("V2 Affirmation (Mail)", True, f"Generated: {filename}, Blob: {blob_url[:50]}...")
    else:
        log_test("V2 Affirmation (Mail)", False, f"Status: {status}, Response: {data}")

def test_v2_affirmation_fax():
    """Test /api/v2/affirmation with fax channel"""
    payload = create_base_letter_payload(channel="fax", fax_number="+1-555-123-4567")
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("V2 Affirmation (Fax)", False, error)
        return
    
    if status == 200:
        blob_url = data.get('blob_url', 'N/A')
        filename = data.get('filename', 'N/A')
        log_test("V2 Affirmation (Fax)", True, f"Generated: {filename}, Blob: {blob_url[:50]}...")
    else:
        log_test("V2 Affirmation (Fax)", False, f"Status: {status}, Response: {data}")

def test_v2_non_affirmation_mail():
    """Test /api/v2/non-affirmation with mail channel"""
    payload = create_base_letter_payload(channel="mail")
    payload["review_codes"] = "0F"
    payload["program_codes"] = "GBC01"
    data, status, error = make_request("POST", "/api/v2/non-affirmation", payload)
    
    if error:
        log_test("V2 Non-Affirmation (Mail)", False, error)
        return
    
    if status == 200:
        blob_url = data.get('blob_url', 'N/A')
        filename = data.get('filename', 'N/A')
        log_test("V2 Non-Affirmation (Mail)", True, f"Generated: {filename}, Blob: {blob_url[:50]}...")
    else:
        log_test("V2 Non-Affirmation (Mail)", False, f"Status: {status}, Response: {data}")

def test_v2_non_affirmation_fax():
    """Test /api/v2/non-affirmation with fax channel"""
    payload = create_base_letter_payload(channel="fax", fax_number="+1-555-123-4567")
    payload["review_codes"] = "0F"
    payload["program_codes"] = "GBC01"
    data, status, error = make_request("POST", "/api/v2/non-affirmation", payload)
    
    if error:
        log_test("V2 Non-Affirmation (Fax)", False, error)
        return
    
    if status == 200:
        blob_url = data.get('blob_url', 'N/A')
        filename = data.get('filename', 'N/A')
        log_test("V2 Non-Affirmation (Fax)", True, f"Generated: {filename}, Blob: {blob_url[:50]}...")
    else:
        log_test("V2 Non-Affirmation (Fax)", False, f"Status: {status}, Response: {data}")

def test_v2_dismissal_mail():
    """Test /api/v2/dismissal with mail channel"""
    payload = create_base_letter_payload(channel="mail")
    payload["denial_reason"] = "Missing required documentation"
    data, status, error = make_request("POST", "/api/v2/dismissal", payload)
    
    if error:
        log_test("V2 Dismissal (Mail)", False, error)
        return
    
    if status == 200:
        blob_url = data.get('blob_url', 'N/A')
        filename = data.get('filename', 'N/A')
        log_test("V2 Dismissal (Mail)", True, f"Generated: {filename}, Blob: {blob_url[:50]}...")
    else:
        log_test("V2 Dismissal (Mail)", False, f"Status: {status}, Response: {data}")

def test_v2_dismissal_fax():
    """Test /api/v2/dismissal with fax channel"""
    payload = create_base_letter_payload(channel="fax", fax_number="+1-555-123-4567")
    payload["denial_reason"] = "Missing required documentation"
    data, status, error = make_request("POST", "/api/v2/dismissal", payload)
    
    if error:
        log_test("V2 Dismissal (Fax)", False, error)
        return
    
    if status == 200:
        blob_url = data.get('blob_url', 'N/A')
        filename = data.get('filename', 'N/A')
        log_test("V2 Dismissal (Fax)", True, f"Generated: {filename}, Blob: {blob_url[:50]}...")
    else:
        log_test("V2 Dismissal (Fax)", False, f"Status: {status}, Response: {data}")

# ============================================================================
# Test Suite 3: Batch Processing Endpoints
# ============================================================================

def test_batch_affirmation():
    """Test /api/v2/batch/affirmation"""
    payload = {
        "letters": [
            create_base_letter_payload(channel="mail"),
            create_base_letter_payload(channel="mail"),
            create_base_letter_payload(channel="fax", fax_number="+1-555-123-4567")
        ]
    }
    data, status, error = make_request("POST", "/api/v2/batch/affirmation", payload)
    
    if error:
        log_test("Batch Affirmation", False, error)
        return
    
    if status == 200:
        results = data.get('results', [])
        success_count = sum(1 for r in results if r.get('success', False))
        log_test("Batch Affirmation", True, f"Processed {success_count}/{len(results)} letters")
    else:
        log_test("Batch Affirmation", False, f"Status: {status}, Response: {data}")

def test_batch_non_affirmation():
    """Test /api/v2/batch/non-affirmation"""
    payload = {
        "letters": [
            {**create_base_letter_payload(channel="mail"), "review_codes": "0F", "program_codes": "GBC01"},
            {**create_base_letter_payload(channel="mail"), "review_codes": "0F", "program_codes": "GBC01"}
        ]
    }
    data, status, error = make_request("POST", "/api/v2/batch/non-affirmation", payload)
    
    if error:
        log_test("Batch Non-Affirmation", False, error)
        return
    
    if status == 200:
        results = data.get('results', [])
        success_count = sum(1 for r in results if r.get('success', False))
        log_test("Batch Non-Affirmation", True, f"Processed {success_count}/{len(results)} letters")
    else:
        log_test("Batch Non-Affirmation", False, f"Status: {status}, Response: {data}")

def test_batch_dismissal():
    """Test /api/v2/batch/dismissal"""
    payload = {
        "letters": [
            {**create_base_letter_payload(channel="mail"), "denial_reason": "Missing documentation"},
            {**create_base_letter_payload(channel="mail"), "denial_reason": "Invalid request"}
        ]
    }
    data, status, error = make_request("POST", "/api/v2/batch/dismissal", payload)
    
    if error:
        log_test("Batch Dismissal", False, error)
        return
    
    if status == 200:
        results = data.get('results', [])
        success_count = sum(1 for r in results if r.get('success', False))
        log_test("Batch Dismissal", True, f"Processed {success_count}/{len(results)} letters")
    else:
        log_test("Batch Dismissal", False, f"Status: {status}, Response: {data}")

# ============================================================================
# Test Suite 4: Error Handling & Validation
# ============================================================================

def test_validation_missing_required_fields():
    """Test validation with missing required fields"""
    payload = {
        "patient_name": "John Doe"
        # Missing patient_id, date, provider_name, channel
    }
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("Validation (Missing Fields)", False, error)
        return
    
    if status == 422:  # Validation error
        log_test("Validation (Missing Fields)", True, f"Correctly rejected with 422")
    else:
        log_test("Validation (Missing Fields)", False, f"Expected 422, got {status}")

def test_validation_invalid_channel():
    """Test validation with invalid channel"""
    payload = create_base_letter_payload(channel="invalid_channel")
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("Validation (Invalid Channel)", False, error)
        return
    
    if status in [400, 422]:
        log_test("Validation (Invalid Channel)", True, f"Correctly rejected with {status}")
    else:
        log_test("Validation (Invalid Channel)", False, f"Expected 400/422, got {status}")

def test_validation_fax_without_number():
    """Test validation for fax channel without fax_number"""
    payload = create_base_letter_payload(channel="fax")
    # Missing fax_number
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("Validation (Fax Without Number)", False, error)
        return
    
    if status in [400, 422]:
        log_test("Validation (Fax Without Number)", True, f"Correctly rejected with {status}")
    else:
        log_test("Validation (Fax Without Number)", False, f"Expected 400/422, got {status}")

def test_invalid_endpoint():
    """Test invalid endpoint"""
    data, status, error = make_request("POST", "/api/v2/invalid-endpoint", {})
    
    if error:
        log_test("Invalid Endpoint", False, error)
        return
    
    if status == 404:
        log_test("Invalid Endpoint", True, f"Correctly returned 404")
    else:
        log_test("Invalid Endpoint", False, f"Expected 404, got {status}")

# ============================================================================
# Test Suite 5: Recovery & Reprocessing Endpoints
# ============================================================================

def test_recovery_health():
    """Test /api/v2/recovery/health"""
    data, status, error = make_request("GET", "/api/v2/recovery/health")
    
    if error:
        log_test("Recovery Health", False, error)
        return
    
    if status == 200:
        log_test("Recovery Health", True, f"Status: {status}")
    else:
        log_test("Recovery Health", False, f"Unexpected status: {status}")

def test_recovery_failed_metadata():
    """Test /api/v2/recovery/failed-metadata"""
    data, status, error = make_request("GET", "/api/v2/recovery/failed-metadata")
    
    if error:
        log_test("Recovery Failed Metadata", False, error)
        return
    
    if status == 200:
        failed_items = data.get('failed_items', [])
        log_test("Recovery Failed Metadata", True, f"Found {len(failed_items)} failed items")
    else:
        log_test("Recovery Failed Metadata", False, f"Status: {status}, Response: {data}")

def test_recovery_process_all_failed():
    """Test /api/v2/recovery/process-all-failed"""
    # This might process actual failed items, so we'll just check if endpoint exists
    data, status, error = make_request("POST", "/api/v2/recovery/process-all-failed", {})
    
    if error:
        log_test("Recovery Process All Failed", False, error)
        return
    
    # This endpoint might return 200 even if no items to process
    if status in [200, 204]:
        processed = data.get('processed_count', 0) if data else 0
        log_test("Recovery Process All Failed", True, f"Processed {processed} items (status: {status})")
    else:
        log_test("Recovery Process All Failed", False, f"Unexpected status: {status}, Response: {data}")

# ============================================================================
# Test Suite 6: Metadata Endpoints
# ============================================================================

def test_fax_metadata_unprocessed():
    """Test /api/v2/fax/metadata/unprocessed"""
    data, status, error = make_request("GET", "/api/v2/fax/metadata/unprocessed")
    
    if error:
        log_test("Fax Metadata (Unprocessed)", False, error)
        return
    
    if status == 200:
        items = data.get('items', []) if isinstance(data, dict) else []
        log_test("Fax Metadata (Unprocessed)", True, f"Found {len(items)} unprocessed items")
    else:
        log_test("Fax Metadata (Unprocessed)", False, f"Status: {status}, Response: {data}")

def test_mail_metadata_unprocessed():
    """Test /api/v2/mail/metadata/unprocessed"""
    data, status, error = make_request("GET", "/api/v2/mail/metadata/unprocessed")
    
    if error:
        log_test("Mail Metadata (Unprocessed)", False, error)
        return
    
    if status == 200:
        items = data.get('items', []) if isinstance(data, dict) else []
        log_test("Mail Metadata (Unprocessed)", True, f"Found {len(items)} unprocessed items")
    else:
        log_test("Mail Metadata (Unprocessed)", False, f"Status: {status}, Response: {data}")

# ============================================================================
# Test Suite 7: Edge Cases & Additional Properties
# ============================================================================

def test_additional_properties():
    """Test that API accepts additional properties (as per API docs)"""
    payload = create_base_letter_payload(channel="mail")
    payload["custom_field_1"] = "Custom Value 1"
    payload["custom_field_2"] = 12345
    payload["decision_tracking_id"] = "TEST-12345"
    payload["provider_npi"] = "1234567890"
    
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("Additional Properties", False, error)
        return
    
    if status == 200:
        log_test("Additional Properties", True, "API accepts additional properties")
    else:
        log_test("Additional Properties", False, f"Status: {status}, Response: {data}")

def test_null_values():
    """Test handling of null values"""
    payload = {
        "patient_name": None,
        "patient_id": None,
        "date": None,
        "provider_name": None,
        "channel": "mail"
    }
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("Null Values", False, error)
        return
    
    # API might accept nulls or reject them - both are valid behaviors
    if status in [200, 400, 422]:
        log_test("Null Values", True, f"Handled null values (status: {status})")
    else:
        log_test("Null Values", False, f"Unexpected status: {status}")

def test_empty_strings():
    """Test handling of empty strings"""
    payload = {
        "patient_name": "",
        "patient_id": "",
        "date": "",
        "provider_name": "",
        "channel": "mail"
    }
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("Empty Strings", False, error)
        return
    
    # API might accept empty strings or reject them - both are valid
    if status in [200, 400, 422]:
        log_test("Empty Strings", True, f"Handled empty strings (status: {status})")
    else:
        log_test("Empty Strings", False, f"Unexpected status: {status}")

# ============================================================================
# Test Suite 8: Response Structure Validation
# ============================================================================

def test_response_structure():
    """Test that response has expected structure"""
    payload = create_base_letter_payload(channel="mail")
    data, status, error = make_request("POST", "/api/v2/affirmation", payload)
    
    if error:
        log_test("Response Structure", False, error)
        return
    
    if status == 200:
        required_fields = ['blob_url', 'filename', 'file_size_bytes', 'generated_at']
        missing_fields = [f for f in required_fields if f not in data]
        
        if missing_fields:
            log_test("Response Structure", False, f"Missing fields: {missing_fields}")
        else:
            log_test("Response Structure", True, "Response has all required fields")
    else:
        log_test("Response Structure", False, f"Status: {status}, Response: {data}")

# ============================================================================
# Main Test Runner
# ============================================================================

def run_all_tests():
    """Run all test suites"""
    print("=" * 80)
    print("Letter Generation API Comprehensive Testing")
    print(f"Base URL: {BASE_URL}")
    print(f"Test Date: {datetime.now().isoformat()}")
    print("=" * 80)
    print()
    
    # Test Suite 1: Health & Version
    print("Test Suite 1: Health & Version Endpoints")
    print("-" * 80)
    test_health_check()
    test_version()
    test_build_info()
    print()
    
    # Test Suite 2: V2 Letter Generation
    print("Test Suite 2: V2 Letter Generation Endpoints")
    print("-" * 80)
    test_v2_affirmation_mail()
    test_v2_affirmation_fax()
    test_v2_non_affirmation_mail()
    test_v2_non_affirmation_fax()
    test_v2_dismissal_mail()
    test_v2_dismissal_fax()
    print()
    
    # Test Suite 3: Batch Processing
    print("Test Suite 3: Batch Processing Endpoints")
    print("-" * 80)
    test_batch_affirmation()
    test_batch_non_affirmation()
    test_batch_dismissal()
    print()
    
    # Test Suite 4: Error Handling
    print("Test Suite 4: Error Handling & Validation")
    print("-" * 80)
    test_validation_missing_required_fields()
    test_validation_invalid_channel()
    test_validation_fax_without_number()
    test_invalid_endpoint()
    print()
    
    # Test Suite 5: Recovery
    print("Test Suite 5: Recovery & Reprocessing Endpoints")
    print("-" * 80)
    test_recovery_health()
    test_recovery_failed_metadata()
    test_recovery_process_all_failed()
    print()
    
    # Test Suite 6: Metadata
    print("Test Suite 6: Metadata Endpoints")
    print("-" * 80)
    test_fax_metadata_unprocessed()
    test_mail_metadata_unprocessed()
    print()
    
    # Test Suite 7: Edge Cases
    print("Test Suite 7: Edge Cases & Additional Properties")
    print("-" * 80)
    test_additional_properties()
    test_null_values()
    test_empty_strings()
    print()
    
    # Test Suite 8: Response Validation
    print("Test Suite 8: Response Structure Validation")
    print("-" * 80)
    test_response_structure()
    print()
    
    # Print Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Passed: {len(test_results['passed'])}")
    print(f"Failed: {len(test_results['failed'])}")
    print(f"Warnings: {len(test_results['warnings'])}")
    print()
    
    if test_results['failed']:
        print("FAILED TESTS:")
        for test in test_results['failed']:
            print(f"  - {test['test']}: {test['message']}")
        print()
    
    if test_results['warnings']:
        print("WARNINGS:")
        for test in test_results['warnings']:
            print(f"  - {test['test']}: {test['message']}")
        print()
    
    # Save results to file
    results_file = Path(__file__).parent / "lettergen_test_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            "test_date": datetime.now().isoformat(),
            "base_url": BASE_URL,
            "summary": {
                "passed": len(test_results['passed']),
                "failed": len(test_results['failed']),
                "warnings": len(test_results['warnings'])
            },
            "results": test_results
        }, f, indent=2)
    
    print(f"Detailed results saved to: {results_file}")
    print()
    
    # Return exit code
    return 0 if len(test_results['failed']) == 0 else 1

if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)

