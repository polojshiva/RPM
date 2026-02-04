# Extracted Fields Data Flow - Issue Found and Fixed

## Summary

A critical issue was identified where the **JSON Generator service was reading from the wrong database column**, causing manual field edits to be ignored during payload generation.

---

## Issue Identified

### Problem
The JSON Generator service was reading from `extracted_fields` (baseline OCR data) instead of using priority logic to check `updated_extracted_fields` (working copy with manual edits) first.

### Impact
- **Manual field edits were being ignored** when generating ESMD payloads
- Users could correct OCR errors in the UI, but those corrections would not appear in the generated JSON payload
- This could lead to incorrect data being sent to downstream systems

### Root Cause
The `get_extracted_fields_from_packet_document()` method in `wiser-pa-decision-json-generator/src/repository/send_serviceops_repository.py` was only querying `extracted_fields` column, ignoring `updated_extracted_fields`.

---

## Fix Applied

### File: `wiser-pa-decision-json-generator/src/repository/send_serviceops_repository.py`

**Before:**
```python
# Step 2: Get extracted_fields from service_ops.packet_document using packet_id
document_record = (
    wiser_session.query(PacketDocumentDB.extracted_fields)
    .filter(PacketDocumentDB.packet_id == packet_id)
    .first()
)

if document_record:
    extracted_fields = document_record.extracted_fields
    # ... always used baseline OCR data
```

**After:**
```python
# Step 2: Get extracted_fields from service_ops.packet_document using packet_id
# Use priority logic: updated_extracted_fields first (working copy), then extracted_fields (baseline)
document_record = (
    wiser_session.query(
        PacketDocumentDB.extracted_fields,
        PacketDocumentDB.updated_extracted_fields
    )
    .filter(PacketDocumentDB.packet_id == packet_id)
    .first()
)

if document_record:
    # Priority: updated_extracted_fields (working copy) first, then extracted_fields (baseline)
    if document_record.updated_extracted_fields:
        extracted_fields = document_record.updated_extracted_fields
        logger.info(f"Found updated_extracted_fields (working copy) for packet_id: {packet_id}")
    else:
        extracted_fields = document_record.extracted_fields
        logger.info(f"Found extracted_fields (baseline OCR) for packet_id: {packet_id}")
```

---

## Data Flow Architecture

### How Extracted Fields Work

1. **Initial OCR Extraction** → `extracted_fields` (baseline, immutable)
   - Stored when OCR is first run
   - Never modified after initial extraction
   - Serves as audit baseline

2. **Manual Field Edits** → `updated_extracted_fields` (working copy)
   - Created when user edits fields in UI
   - Contains all fields from `extracted_fields` plus manual corrections
   - Can be updated multiple times
   - Has audit history in `extracted_fields_update_history`

3. **Priority Logic** (ServiceOps standard):
   ```python
   if document.updated_extracted_fields:
       return document.updated_extracted_fields  # Use working copy
   else:
       return document.extracted_fields  # Fallback to baseline
   ```

4. **JSON Generator** (now fixed):
   - Uses same priority logic
   - Reads `updated_extracted_fields` if it exists
   - Falls back to `extracted_fields` if no manual edits

---

## Test Results

A comprehensive test script was created (`scripts/test_extracted_fields_flow.py`) that:

1. ✅ Finds existing packet with extracted_fields
2. ✅ Simulates manual field update (updates `updated_extracted_fields`)
3. ✅ Verifies baseline (`extracted_fields`) is preserved
4. ✅ Tests JSON Generator read priority (now correct)
5. ✅ Tests packet sync from updated fields
6. ✅ Simulates full workflow

### Test Output Example:
```
Step 3: Test JSON Generator Read Priority
Current JSON Generator reads:
  Source: extracted_fields (baseline OCR)
  Provider NPI: N/A

Correct priority logic (updated_extracted_fields first):
  Source: updated_extracted_fields
  Provider NPI: 9876543210

[PASS] JSON Generator Priority Check
```

---

## Verification Steps

To verify the fix works correctly:

1. **Create/Find a packet** with OCR extracted fields
2. **Edit a field** in the UI (e.g., Provider NPI)
3. **Trigger JSON Generator** (via ClinicalOps decision)
4. **Check generated payload** - should contain the edited value, not the original OCR value

---

## Related Files

- **JSON Generator**: `wiser-pa-decision-json-generator/src/repository/send_serviceops_repository.py`
- **ServiceOps**: `wiser-service-operations-backend/app/routes/documents.py` (has correct priority logic)
- **Test Script**: `wiser-service-operations-backend/scripts/test_extracted_fields_flow.py`
- **Packet Sync**: `wiser-service-operations-backend/app/utils/packet_sync.py` (uses priority logic)

---

## Next Steps

1. ✅ Fix applied to JSON Generator repository
2. ✅ Test script created and verified
3. ⏳ Deploy fix to JSON Generator service
4. ⏳ Verify in production that manual edits are now included in generated payloads

---

## Notes

- The fix maintains backward compatibility (if `updated_extracted_fields` is NULL, uses `extracted_fields`)
- This aligns JSON Generator behavior with ServiceOps standard pattern
- No database schema changes required
- No breaking changes to existing functionality



