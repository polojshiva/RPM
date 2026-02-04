#!/usr/bin/env python3
"""
Quick verification script to check if N3941 fix is working.
Run this to verify the code is correct before/after restarting the service.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.field_validation_service import (
    validate_diagnosis_code_requirement,
    REQUIRED_DIAGNOSIS_PROCEDURES
)

print("=" * 80)
print("Verifying N3941 Fix")
print("=" * 80)

# Check 1: Is N3941 in the allowed list?
print("\n1. Checking if N3941 is in allowed diagnosis codes...")
n3941_in_list = 'N3941' in REQUIRED_DIAGNOSIS_PROCEDURES['vagus_nerve_stimulation']['required_diagnosis_codes']
print(f"   N3941 in vagus_nerve_stimulation codes: {n3941_in_list}")

if n3941_in_list:
    print("   [OK] N3941 is in the allowed list")
else:
    print("   [ERROR] N3941 is NOT in the allowed list - fix not applied!")

# Check 2: Does validation accept N3941?
print("\n2. Testing validation with N3941 and procedure code 64561...")
errors = validate_diagnosis_code_requirement(
    diagnosis_code='N3941',
    procedure_codes=['64561'],
    part_type='PART_B'
)

if len(errors) == 0:
    print("   [OK] Validation accepts N3941 - no errors returned")
    print("   [OK] Fix is working correctly!")
else:
    print(f"   [ERROR] Validation still rejects N3941:")
    for error in errors:
        print(f"     - {error}")
    print("   [ERROR] Fix is NOT working - check if service was restarted")

# Check 3: Test with period (N39.41)
print("\n3. Testing validation with N39.41 (with period)...")
errors_with_period = validate_diagnosis_code_requirement(
    diagnosis_code='N39.41',
    procedure_codes=['64561'],
    part_type='PART_B'
)

if len(errors_with_period) == 0:
    print("   [OK] Validation accepts N39.41 (with period) - no errors returned")
else:
    print(f"   [WARN] Validation rejects N39.41:")
    for error in errors_with_period:
        print(f"     - {error}")

print("\n" + "=" * 80)
print("Summary")
print("=" * 80)

if n3941_in_list and len(errors) == 0:
    print("[SUCCESS] N3941 fix is working correctly!")
    print("\nIf users still see errors:")
    print("  1. Backend service needs to be restarted to load new code")
    print("  2. Old records need to be re-validated (run revalidate script)")
    print("  3. Users can save the field again to trigger re-validation")
else:
    print("[ERROR] N3941 fix is NOT working!")
    print("  - Check if code was deployed correctly")
    print("  - Check if service was restarted")
    print("  - Verify the fix is in the codebase")
