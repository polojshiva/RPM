"""
Test script to verify FAX container extraction from blob paths.

This script tests the _extract_container_from_blob_path() method and
_construct_source_absolute_url() method to ensure FAX payloads with container
names in blobPath are correctly parsed.

Run: python scripts/test_fax_container_extraction.py
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.payload_parser import PayloadParser

def test_extract_container_from_blob_path():
    """Test container extraction from blob paths"""
    print("=" * 80)
    print("Testing _extract_container_from_blob_path()")
    print("=" * 80)
    
    test_cases = [
        # (blob_path, expected_result, description)
        (
            "integration-inbound-fax/2026/01-15/uuid-123/file.pdf",
            ("integration-inbound-fax", "2026/01-15/uuid-123/file.pdf"),
            "FAX path with container prefix"
        ),
        (
            "esmd-download/2026/01-15/uuid-456/document.pdf",
            ("esmd-download", "2026/01-15/uuid-456/document.pdf"),
            "ESMD path with container prefix"
        ),
        (
            "2026/01-15/uuid-789/file.pdf",
            None,
            "Path without container (should return None)"
        ),
        (
            "/integration-inbound-fax/2026/01-15/file.pdf",
            ("integration-inbound-fax", "2026/01-15/file.pdf"),
            "FAX path with leading slash"
        ),
        (
            "INTEGRATION-INBOUND-FAX/2026/01-15/file.pdf",
            ("integration-inbound-fax", "2026/01-15/file.pdf"),
            "FAX path with uppercase (case-insensitive)"
        ),
        (
            "",
            None,
            "Empty path"
        ),
        (
            None,
            None,
            "None path"
        ),
    ]
    
    passed = 0
    failed = 0
    
    for blob_path, expected, description in test_cases:
        try:
            result = PayloadParser._extract_container_from_blob_path(blob_path)
            
            if result == expected:
                print(f"[PASS] {description}")
                print(f"       Input: {blob_path}")
                print(f"       Result: {result}")
                passed += 1
            else:
                print(f"[FAIL] {description}")
                print(f"       Input: {blob_path}")
                print(f"       Expected: {expected}")
                print(f"       Got: {result}")
                failed += 1
        except Exception as e:
            print(f"[ERROR] {description}")
            print(f"       Input: {blob_path}")
            print(f"       Error: {e}")
            failed += 1
        print()
    
    print("=" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)
    
    return failed == 0

def test_construct_source_absolute_url_with_container():
    """Test URL construction with container extraction"""
    print("\n" + "=" * 80)
    print("Testing _construct_source_absolute_url() with container extraction")
    print("=" * 80)
    
    # Mock settings for testing
    from app.config import settings
    original_storage_url = settings.storage_account_url
    original_source_container = settings.azure_storage_source_container
    
    # Set test values
    settings.storage_account_url = "https://teststorage.blob.core.windows.net"
    settings.azure_storage_source_container = "default-container"
    
    try:
        test_cases = [
            # (blob_path, expected_container_in_url, description)
            (
                "integration-inbound-fax/2026/01-15/file.pdf",
                "integration-inbound-fax",
                "FAX path with container - should use extracted container"
            ),
            (
                "2026/01-15/file.pdf",
                "default-container",
                "Path without container - should use env var"
            ),
        ]
        
        passed = 0
        failed = 0
        
        for blob_path, expected_container, description in test_cases:
            try:
                url = PayloadParser._construct_source_absolute_url(
                    extraction_path=None,
                    file_name="file.pdf",
                    relative_path=None,
                    blob_path=blob_path
                )
                
                if expected_container in url:
                    print(f"[PASS] {description}")
                    print(f"       Input blob_path: {blob_path}")
                    print(f"       Generated URL: {url}")
                    print(f"       Container used: {expected_container}")
                    passed += 1
                else:
                    print(f"[FAIL] {description}")
                    print(f"       Input blob_path: {blob_path}")
                    print(f"       Generated URL: {url}")
                    print(f"       Expected container in URL: {expected_container}")
                    failed += 1
            except Exception as e:
                print(f"[ERROR] {description}")
                print(f"       Input blob_path: {blob_path}")
                print(f"       Error: {e}")
                failed += 1
            print()
        
        print("=" * 80)
        print(f"Results: {passed} passed, {failed} failed")
        print("=" * 80)
        
        return failed == 0
        
    finally:
        # Restore original settings
        settings.storage_account_url = original_storage_url
        settings.azure_storage_source_container = original_source_container

def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("FAX Container Extraction Test Suite")
    print("=" * 80)
    
    test1_passed = test_extract_container_from_blob_path()
    test2_passed = test_construct_source_absolute_url_with_container()
    
    print("\n" + "=" * 80)
    print("Overall Results")
    print("=" * 80)
    
    if test1_passed and test2_passed:
        print("[SUCCESS] All tests passed!")
        print("\nThe FAX container extraction fix is working correctly.")
        return 0
    else:
        print("[FAILURE] Some tests failed.")
        print("Please review the test output above.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)



