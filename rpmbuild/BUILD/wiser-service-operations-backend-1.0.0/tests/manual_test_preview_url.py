"""
Manual test script for preview URL generation
Run this after starting the server to verify the fix works

Usage:
1. Start the server: uvicorn app.main:app --host 0.0.0.0 --port 4000
2. Run this script: python tests/manual_test_preview_url.py
"""
import requests
import json

BASE_URL = "http://localhost:4000"
PACKET_ID = "PKT-2026-817726"
DOC_ID = "DOC-265"
PAGE_NUM = 1

def test_http_request():
    """Test with plain HTTP request"""
    print("\n=== Test 1: Plain HTTP Request ===")
    url = f"{BASE_URL}/api/packets/{PACKET_ID}/documents/{DOC_ID}/pages/{PAGE_NUM}/preview"
    headers = {"Authorization": "Bearer test-token"}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            preview_url = data.get("data", {}).get("previewUrl", "")
            print(f"Preview URL: {preview_url}")
            if preview_url.startswith("http://"):
                print("✓ Correct: URL uses HTTP scheme")
            else:
                print(f"⚠ Unexpected scheme: {preview_url}")
        else:
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")


def test_https_with_forwarded_proto():
    """Test with X-Forwarded-Proto: https header"""
    print("\n=== Test 2: HTTPS with X-Forwarded-Proto ===")
    url = f"{BASE_URL}/api/packets/{PACKET_ID}/documents/{DOC_ID}/pages/{PAGE_NUM}/preview"
    headers = {
        "Authorization": "Bearer test-token",
        "X-Forwarded-Proto": "https",
        "Host": "prd-wiser-ops-appb.azurewebsites.us"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            preview_url = data.get("data", {}).get("previewUrl", "")
            print(f"Preview URL: {preview_url}")
            if preview_url.startswith("https://"):
                print("✓ Correct: URL uses HTTPS scheme")
                if "prd-wiser-ops-appb.azurewebsites.us" in preview_url:
                    print("✓ Correct: URL uses forwarded host")
                else:
                    print(f"⚠ Host mismatch: {preview_url}")
            else:
                print(f"✗ ERROR: URL should use HTTPS but got: {preview_url}")
        else:
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("Preview URL Generation Manual Test")
    print("=" * 60)
    print(f"Testing against: {BASE_URL}")
    print(f"Packet: {PACKET_ID}, Document: {DOC_ID}, Page: {PAGE_NUM}")
    print("\nNote: These tests require:")
    print("  1. Server running on localhost:4000")
    print("  2. Valid authentication token")
    print("  3. Test data in database")
    print("=" * 60)
    
    test_http_request()
    test_https_with_forwarded_proto()
    
    print("\n" + "=" * 60)
    print("Manual test complete")
    print("=" * 60)






