# Generated Payload Processing Implementation

## Summary

This implementation updates ServiceOps to process generated payloads from the JSON Generator service instead of generating ESMD payloads internally. The JSON Generator service writes the generated payload to both `send_integration` (for Integration service) and `send_serviceops` (for ServiceOps to read and update status).

## Changes Made

### 1. Database Migration

**File**: `deploy/migrations/022_add_json_sent_to_integration_flag.sql`

- Added `json_sent_to_integration` column to `service_ops.send_serviceops` table
- Column type: `BOOLEAN DEFAULT FALSE`
- `NULL` = not a generated payload, `TRUE` = sent successfully, `FALSE` = failed to send
- Created index for faster lookups

### 2. Model Updates

**File**: `app/models/clinical_ops_db.py`

- Added `json_sent_to_integration` field to `ClinicalOpsInboxDB` model
- Updated docstring to reflect new purpose (stores generated payloads from JSON Generator)

### 3. Processor Updates

**File**: `app/services/clinical_ops_inbox_processor.py`

#### Key Changes:

1. **Updated Polling Query**:
   - Changed from filtering `payload->>'message_type' = 'CLINICAL_DECISION'`
   - Now filters `json_sent_to_integration IS NOT NULL`
   - Only processes generated payloads from JSON Generator

2. **New Method: `_extract_decision_from_generated_payload()`**:
   - Extracts decision data from JSON Generator's generated payload
   - Maps `decisionIndicator` ("A"/"N") to `decision_outcome` ("AFFIRM"/"NON_AFFIRM")
   - Determines Direct PA vs Standard PA based on `esmdTransactionId` presence
   - Extracts procedures, part type, documentation, etc.

3. **Replaced `_handle_clinical_decision()` with `_handle_generated_payload()`**:
   - Removed ESMD payload generation (no longer needed)
   - Removed writing to `send_integration` (JSON Generator does this)
   - Now extracts decision from generated payload
   - Updates `packet_decision` with ESMD tracking
   - Sets `esmd_request_status` based on `json_sent_to_integration` flag
   - Updates packet status accordingly

4. **Updated `_process_message()`**:
   - Now processes generated payloads instead of CLINICAL_DECISION messages
   - Routes to `_handle_generated_payload()` handler

### 4. Unit Tests

**File**: `tests/test_generated_payload_processing.py`

- **13 comprehensive unit tests** covering:
  - Decision extraction (AFFIRM/NON_AFFIRM)
  - Direct PA vs Standard PA detection
  - Part A vs Part B handling
  - Multiple procedures
  - Error handling (missing procedures, invalid indicators, etc.)
  - Success and failure scenarios
  - Missing packet validation

**All tests passing**: ✅ 13/13

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: ServiceOps sends case to ClinicalOps              │
│ service_ops.send_clinicalops                                │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: ClinicalOps makes decision in their system         │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: ClinicalOps triggers JSON Generator endpoint      │
│ POST /decision/generate_payload_json                        │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: JSON Generator creates payload                    │
│ - Reads from integration.send_serviceops                   │
│ - Reads from DDMS                                          │
│ - Reads from packet_document (OCR fields)                  │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 5: JSON Generator writes to send_integration FIRST   │
│ service_ops.send_integration                                │
│ - payload: { generated_payload }                           │
│ - message_status_id: 3 (SENT)                              │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 6: JSON Generator writes SAME payload to send_serviceops│
│ service_ops.send_serviceops (NEW RECORD)                    │
│ - payload: { SAME generated_payload }                     │
│ - json_sent_to_integration: true/false                     │
│ - message_status_id: 3 (SENT)                              │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 7: ServiceOps reads from send_serviceops              │
│ - Polls for json_sent_to_integration IS NOT NULL          │
│ - Extracts decision from generated payload                 │
│ - Updates packet_decision and status                       │
│ - Skips JSON generation (already done)                     │
└─────────────────────────────────────────────────────────────┘
```

## Generated Payload Structure

The JSON Generator sends payloads in this format:

```json
{
  "header": {
    "icd": "0",
    "state": "NJ",
    "physician": { ... },
    "beneficiary": { ... },
    "facilityOrRenderingProvider": { ... }
  },
  "partType": "B",
  "procedures": [
    {
      "procedureCode": "69799",
      "decisionIndicator": "N",  // "A" = AFFIRM, "N" = NON_AFFIRM
      "mrCountUnitOfService": "1",
      "placeOfService": "19",
      "reviewCodes": ["GAA02"],
      "programCodes": ["04", "0C"]
    }
  ],
  "esmdTransactionId": "MMR000a80914EC",  // Present for Standard PA
  "documentation": ["path/to/letter.pdf"]
}
```

## Decision Extraction Logic

- **Decision Outcome**: Extracted from `procedures[0].decisionIndicator`
  - `"A"` → `"AFFIRM"`
  - `"N"` → `"NON_AFFIRM"`

- **Direct PA vs Standard PA**: Determined by `esmdTransactionId` presence
  - Has `esmdTransactionId` → `STANDARD_PA`
  - No `esmdTransactionId` → `DIRECT_PA`

- **Part Type**: Directly from `partType` field ("A" or "B")

- **Procedures**: Converted from JSON Generator format to internal format

## Error Handling

1. **Missing Procedures**: Raises `ValueError` if procedures array is missing or empty
2. **Invalid Decision Indicator**: Raises `ValueError` if `decisionIndicator` is not "A" or "N"
3. **Missing Packet**: Raises `ValueError` if packet not found for `decision_tracking_id`
4. **Failed Send**: If `json_sent_to_integration = false`, sets status to "Generate Decision Letter - Pending" and stops workflow

## Testing

### Unit Tests
- ✅ 13/13 tests passing
- Covers all extraction scenarios
- Covers error cases
- Covers success and failure paths

### Test Coverage
- Decision extraction (AFFIRM/NON_AFFIRM)
- Direct PA vs Standard PA detection
- Part A vs Part B handling
- Multiple procedures
- Error handling
- Missing packet validation
- Failed send handling

## Migration Instructions

1. **Run Migration**:
   ```sql
   -- Run migration 022
   \i deploy/migrations/022_add_json_sent_to_integration_flag.sql
   ```

2. **Verify Column**:
   ```sql
   SELECT column_name, data_type, is_nullable, column_default
   FROM information_schema.columns
   WHERE table_schema = 'service_ops'
     AND table_name = 'send_serviceops'
     AND column_name = 'json_sent_to_integration';
   ```

3. **Verify Index**:
   ```sql
   SELECT indexname, indexdef
   FROM pg_indexes
   WHERE schemaname = 'service_ops'
     AND tablename = 'send_serviceops'
     AND indexname = 'idx_send_serviceops_json_sent';
   ```

## Backward Compatibility

- **Old CLINICAL_DECISION messages**: Will be ignored (not processed)
- **Existing records**: `json_sent_to_integration` will be `NULL` for old records
- **No breaking changes**: Old records remain in database, just not processed

## Benefits

1. **Single Source of Truth**: JSON Generator owns payload generation
2. **No Duplicate Logic**: ServiceOps no longer generates ESMD payloads
3. **Clear Tracking**: `json_sent_to_integration` flag indicates success/failure
4. **Simplified Flow**: ServiceOps just reads and updates status
5. **Better Separation**: ClinicalOps triggers, JSON Generator generates, ServiceOps updates

## Next Steps

1. **JSON Generator Team**: Must implement writing to `send_serviceops` with `json_sent_to_integration` flag
2. **Integration Testing**: Test end-to-end flow with actual JSON Generator service
3. **Monitoring**: Add metrics for generated payload processing
4. **Fallback**: Consider UI button for manual payload generation if JSON Generator fails

