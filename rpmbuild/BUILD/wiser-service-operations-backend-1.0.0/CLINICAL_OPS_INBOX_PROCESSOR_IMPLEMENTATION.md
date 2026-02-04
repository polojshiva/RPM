# ClinicalOps Inbox Processor - Phase 1 → Phase 2 Implementation

## Summary

Updated `ClinicalOpsInboxProcessor` to automatically trigger JSON Generator Phase 2 when Phase 1 records are detected, then process the generated payloads.

## Flow

```
1. ClinicalOps makes decision → Calls Phase 1 endpoint
   POST /decision/generate_clinical_ops_decision_json
   ↓
2. Phase 1 writes to send_serviceops:
   - clinical_ops_decision_json = {...}
   - json_sent_to_integration = NULL
   ↓
3. ServiceOps polls send_serviceops:
   - Finds Phase 1 record (clinical_ops_decision_json IS NOT NULL, json_sent_to_integration IS NULL)
   - Automatically calls Phase 2 endpoint
   POST /decision/generate_payload_json
   ↓
4. JSON Generator Phase 2:
   - Generates ESMD payload
   - Writes to send_integration
   - Writes to send_serviceops (json_sent_to_integration = TRUE/FALSE)
   ↓
5. ServiceOps polls again:
   - Finds Phase 2 record (json_sent_to_integration IS NOT NULL)
   - Processes the generated payload
   - Updates packet_decision, status, etc.
   ↓
6. Integration picks up from send_integration
```

## Changes Made

### 1. Configuration (`app/config/settings.py`)
- Added `json_generator_base_url: str = ""` - Base URL for JSON Generator service
- Added `json_generator_timeout_seconds: int = 60` - Request timeout

### 2. Model Update (`app/models/clinical_ops_db.py`)
- Added `clinical_ops_decision_json = Column(JSONB, nullable=True)` to `ClinicalOpsInboxDB`
- This column stores Phase 1 data written by JSON Generator

### 3. Processor Update (`app/services/clinical_ops_inbox_processor.py`)

#### Updated `_poll_new_messages()`:
- Now polls for BOTH Phase 1 and Phase 2 records
- Checks if `clinical_ops_decision_json` column exists (graceful degradation)
- Phase 1: `clinical_ops_decision_json IS NOT NULL AND json_sent_to_integration IS NULL`
- Phase 2: `json_sent_to_integration IS NOT NULL`

#### Added `_call_json_generator_phase2()`:
- HTTP client method to call JSON Generator Phase 2 endpoint
- Uses `httpx.AsyncClient` with configurable timeout
- Returns `True` if successful, `False` otherwise
- Logs errors for debugging

#### Updated `_process_message()`:
- Handles TWO scenarios:
  1. **Phase 1**: Calls JSON Generator Phase 2 endpoint automatically
  2. **Phase 2**: Processes the generated payload (existing logic)

## Database Migration Required

The `clinical_ops_decision_json` column needs to be added to `service_ops.send_serviceops` table:

```sql
ALTER TABLE service_ops.send_serviceops
ADD COLUMN IF NOT EXISTS clinical_ops_decision_json JSONB;

COMMENT ON COLUMN service_ops.send_serviceops.clinical_ops_decision_json IS 
    'Phase 1: Clinical decision data stored by JSON Generator. NULL = not Phase 1, JSONB = Phase 1 data';
```

**Note**: The code gracefully handles the missing column by:
- Checking if column exists before querying
- Falling back to Phase 2-only processing if column doesn't exist
- Logging a warning message

## Configuration Required

Set environment variable:
```bash
JSON_GENERATOR_BASE_URL=https://prd-wiser-pa-decision-payload-json-generator.azurewebsites.us
```

Or in `.env` file:
```
JSON_GENERATOR_BASE_URL=https://prd-wiser-pa-decision-payload-json-generator.azurewebsites.us
```

## Testing

Run the test script:
```bash
python scripts/test_clinical_ops_inbox_processor.py
```

**Test Results**:
- ✅ Phase 2 Detection: Working (found 2 records)
- ✅ Poll Query: Working (gracefully handles missing column)
- ✅ Message Processing Logic: Working
- ⚠️ Phase 1 Detection: Requires `clinical_ops_decision_json` column migration
- ⚠️ JSON Generator Config: Requires `JSON_GENERATOR_BASE_URL` env var

## Key Features

1. **Automatic Phase 2 Triggering**: No manual intervention needed
2. **Graceful Degradation**: Works even if `clinical_ops_decision_json` column doesn't exist yet
3. **Error Handling**: Logs errors and retries Phase 1 records in next poll cycle
4. **Idempotent**: Safe to run multiple times (watermark tracking)
5. **Backward Compatible**: Still processes Phase 2 records (existing behavior)

## Next Steps

1. **Add Database Migration**: Create migration to add `clinical_ops_decision_json` column
2. **Set Environment Variable**: Configure `JSON_GENERATOR_BASE_URL` in production
3. **Monitor Logs**: Watch for Phase 1 → Phase 2 transitions in production
4. **Verify Integration**: Confirm Integration service picks up from `send_integration`

## Removed Logic

- **No internal ESMD generation**: All payload generation now goes through JSON Generator
- **Simplified flow**: Direct Phase 1 → Phase 2 → Process pipeline
