# Re-validate Packets in Production - Guide

## Problem
After deploying validation fixes (e.g., N3941 diagnosis code fix, city validation word boundary fix), **existing packets in the database still have old validation errors** stored. These packets need to be re-validated with the new code.

## Solution
Use the `revalidate_all_packets_with_errors.py` script to re-validate all packets that currently have validation errors.

## Scripts Available

### 1. Re-validate All Packets with Errors
**Script:** `scripts/revalidate_all_packets_with_errors.py`

**What it does:**
- Finds all packets with `has_field_validation_errors = true`
- Re-runs validation with the latest code
- Updates validation flags and creates new validation records
- Maintains audit trail (doesn't delete old validation records)

**Usage:**

```bash
# Dry run (see what would be re-validated without making changes)
python scripts/revalidate_all_packets_with_errors.py --dry-run

# Re-validate all packets with errors
python scripts/revalidate_all_packets_with_errors.py

# Re-validate a specific packet
python scripts/revalidate_all_packets_with_errors.py <packet_id>
```

**Example:**
```bash
# Check what would be re-validated
python scripts/revalidate_all_packets_with_errors.py --dry-run

# Actually re-validate all packets
python scripts/revalidate_all_packets_with_errors.py

# Re-validate specific packet
python scripts/revalidate_all_packets_with_errors.py SVC-2026-975319
```

### 2. Re-validate Packets with N3941
**Script:** `scripts/revalidate_packets_with_n3941.py`

**What it does:**
- Finds all packets that have N3941 in their diagnosis codes
- Re-validates them (useful after N3941 fix deployment)

**Usage:**
```bash
# Re-validate all packets with N3941
python scripts/revalidate_packets_with_n3941.py

# Re-validate specific packet
python scripts/revalidate_packets_with_n3941.py <packet_id>
```

## Production Deployment Steps

### Step 1: Deploy Code
Deploy the validation fixes to production (N3941 fix, city validation fix, etc.)

### Step 2: Verify Deployment
Verify the new code is running:
```bash
# Check if N3941 is in allowed codes
python -c "from app.services.field_validation_service import REQUIRED_DIAGNOSIS_PROCEDURES; print('N3941' in REQUIRED_DIAGNOSIS_PROCEDURES['vagus_nerve_stimulation']['required_diagnosis_codes'])"
# Should print: True
```

### Step 3: Dry Run (Recommended)
Run a dry run to see what would be re-validated:
```bash
python scripts/revalidate_all_packets_with_errors.py --dry-run
```

### Step 4: Re-validate All Packets
Run the script to re-validate all packets with errors:
```bash
python scripts/revalidate_all_packets_with_errors.py
```

**Expected Output:**
```
================================================================================
Re-validating packets with validation errors
================================================================================

Found 4 packet(s) with validation errors to re-validate

Processing: SVC-2026-975319 (packet_id: 123)
  [FIXED] Validation errors cleared!

Processing: SVC-2026-975320 (packet_id: 124)
  [WARN] Still has validation errors:
    - state: State must be NJ. Current: NY

================================================================================
Re-validation complete!
================================================================================
Total packets processed: 4
Fixed (errors cleared): 2
Still has errors: 2
Errors (failed to process): 0
No errors (already correct): 0
```

## Safety Features

✅ **Production-Safe:**
- Only re-validates packets that already have validation errors
- Creates new validation records (maintains audit trail)
- Handles errors gracefully and continues processing
- Can be run multiple times safely (idempotent)
- Dry-run mode available

✅ **Audit Trail:**
- Old validation records are marked as `is_active = false`
- New validation records are created with `is_active = true`
- All validation history is preserved

✅ **Error Handling:**
- If one packet fails, others continue processing
- Detailed logging for troubleshooting
- Rollback on errors (per packet)

## Alternative: User-Triggered Re-validation

**Note:** Users can also trigger re-validation by:
1. Opening a packet with validation errors
2. Editing any field (even if unchanged)
3. Clicking "Save"

This will automatically re-validate with the latest code and clear old errors.

## Monitoring

After running the script, check:
1. **Packets Dashboard:** Validation error icons should disappear for fixed packets
2. **Database:** `packet.has_field_validation_errors` should be updated
3. **Validation Table:** New validation records should be created

## Troubleshooting

### Script fails with database connection error
- Check database connection settings
- Ensure database is accessible from the server

### Some packets still show errors after re-validation
- These packets likely have other validation errors (not related to the fix)
- Check the validation output for specific error messages

### Script is slow
- Normal for large datasets
- Consider running during off-peak hours
- Can be run in batches if needed (modify script to add LIMIT/OFFSET)

## Example: Re-validate After N3941 Fix

```bash
# 1. Deploy N3941 fix to production
# 2. Verify code is deployed
python -c "from app.services.field_validation_service import REQUIRED_DIAGNOSIS_PROCEDURES; print('N3941' in REQUIRED_DIAGNOSIS_PROCEDURES['vagus_nerve_stimulation']['required_diagnosis_codes'])"

# 3. Dry run
python scripts/revalidate_all_packets_with_errors.py --dry-run

# 4. Re-validate all packets
python scripts/revalidate_all_packets_with_errors.py

# 5. Verify results
# Check packets dashboard - validation errors should be cleared for packets with N3941
```

## Support

If you encounter issues:
1. Check the script logs for error messages
2. Verify the validation code is correct (run the verification command above)
3. Check database connectivity
4. Review the validation output for specific error messages
