# PA JSON Generator Service Integration Analysis

## Executive Summary

**Current Situation**: There are TWO separate services generating ESMD payloads:
1. **ServiceOps Backend** - Currently generates ESMD payloads internally using `EsmdPayloadGenerator`
2. **PA JSON Generator Service** - New microservice that generates payloads via HTTP endpoint

**Key Finding**: These services use DIFFERENT data sources and approaches, but both write to the same `service_ops.send_integration` table.

---

## Current Implementation (ServiceOps Backend)

### Flow:
```
1. ClinicalOps writes decision → service_ops.send_serviceops
   └─> payload: { "message_type": "CLINICAL_DECISION", "decision_outcome": "AFFIRM", ... }

2. ClinicalOpsInboxProcessor reads from service_ops.send_serviceops
   └─> Processes CLINICAL_DECISION message

3. Extracts decision data from payload:
   └─> decision_outcome (AFFIRM/NON_AFFIRM)
   └─> decision_subtype (DIRECT_PA/STANDARD_PA)
   └─> part_type (A/B)
   └─> procedures array
   └─> medical_documents array

4. Calls EsmdPayloadGenerator.generate_payload()
   └─> Uses packet data
   └─> Uses packet_decision data
   └─> Uses extracted_fields from packet_document
   └─> Generates ESMD-compliant JSON

5. Writes to service_ops.send_integration
   └─> payload: { "message_type": "ESMD_PAYLOAD", "esmd_payload": {...}, ... }
```

### Location:
- **File**: `wiser-service-operations-backend/app/services/clinical_ops_inbox_processor.py`
- **Method**: `_handle_clinical_decision()`
- **Lines**: 235-406

### Data Sources:
- `service_ops.packet` - Packet data
- `service_ops.packet_decision` - Decision data (from ClinicalOps payload)
- `service_ops.packet_document` - Extracted fields (OCR data)
- ClinicalOps payload - Decision outcome, subtype, procedures, medical docs

---

## New Implementation (PA JSON Generator Service)

### Flow:
```
1. ClinicalOps writes decision → service_ops.send_serviceops (same as current)
   └─> payload: { "message_type": "CLINICAL_DECISION", ... }

2. ClinicalOps (or trigger) calls PA JSON Generator endpoint:
   └─> POST /decision/generate_payload_json
   └─> Request: { "decision_tracking_id": "..." }

3. PA JSON Generator performs 8 steps:
   Step 1: Get message_type_id from integration.send_serviceops
           └─> Reads from integration.send_serviceops (DIFFERENT TABLE!)
           └─> Gets message_type_id column
   
   Step 2: Get code from integration.message_type table
           └─> Uses message_type_id to get code (e.g., "PA", "UTN")
   
   Step 3: Get decision status from DDMS claim table
           └─> Reads from DDMS database (external system)
           └─> Gets claimStatus (Approved/Rejected)
           └─> Converts to decision_indicator (A/N)
   
   Step 4: Get extracted_fields from service_ops.packet_document
           └─> Same as current implementation
   
   Step 5: Get claimId and failed reason data
           └─> Reads from DDMS failedReason table
           └─> Maps to reviewCodes and programCodes
   
   Step 6: Generate JSON payload using PayloadGenerationService
           └─> Uses message_type_code ("PA" or "UTN")
           └─> Uses extracted_fields
           └─> Uses decision_indicator (from DDMS, not ClinicalOps!)
           └─> Generates ESMD-compliant JSON
   
   Step 7: Create/update workflow_instance
           └─> Creates entry in service_ops.workflow_instance
   
   Step 8: Write to service_ops.send_integration
           └─> payload: { "message_type": "PA", "payload_type": "PA", ... }
           └─> Sets message_status_id = 3 (SENT)
```

### Location:
- **Service**: `wiser-pa-decision-json-generator`
- **Endpoint**: `POST /decision/generate_payload_json`
- **File**: `wiser-pa-decision-json-generator/src/api/router.py` (line 177)
- **Controller**: `wiser-pa-decision-json-generator/src/controller/decision_controller.py`
- **Method**: `generate_payload_json()` (line 474)

### Data Sources:
- `integration.send_serviceops` - **DIFFERENT TABLE** (has message_type_id column)
- `integration.message_type` - Message type lookup
- `DDMS.claim` - Decision status (external database)
- `DDMS.failedReason` - Review/program codes
- `service_ops.packet_document` - Extracted fields (same as current)
- `service_ops.workflow_instance` - Workflow tracking

---

## Key Differences

### 1. Data Source for Decision Indicator

**Current (ServiceOps Backend)**:
- Gets decision from ClinicalOps payload directly
- `decision_outcome` = "AFFIRM" or "NON_AFFIRM" (from ClinicalOps)
- Uses this to set `priorAuthDecision` in ESMD payload

**New (PA JSON Generator)**:
- Gets decision from DDMS claim table
- Reads `claimStatus` from `DDMS.claim` table
- Converts: "Approved" → "A", "Rejected" → "N"
- Uses this as `decision_indicator` in payload generation

**Issue**: These may not match! ClinicalOps decision vs DDMS claim status could differ.

### 2. Message Type Determination

**Current (ServiceOps Backend)**:
- Always generates "ESMD_PAYLOAD" message_type
- Determines Direct/Standard PA from `decision_subtype` in ClinicalOps payload

**New (PA JSON Generator)**:
- Reads `message_type_id` from `integration.send_serviceops` table
- Gets code from `integration.message_type` table ("PA" or "UTN")
- Uses code to determine payload type

**Issue**: Requires `integration.send_serviceops` to have correct `message_type_id` set.

### 3. Table Usage

**Current (ServiceOps Backend)**:
- Reads from: `service_ops.send_serviceops` (ClinicalOps inbox)
- Writes to: `service_ops.send_integration`

**New (PA JSON Generator)**:
- Reads from: `integration.send_serviceops` (DIFFERENT TABLE!)
- Also reads from: `service_ops.send_serviceops` (for message_type_id lookup)
- Writes to: `service_ops.send_integration` (same table)

**Issue**: Two different `send_serviceops` tables in different schemas!

### 4. Workflow Instance

**Current (ServiceOps Backend)**:
- Does NOT create workflow_instance
- Just writes to send_integration

**New (PA JSON Generator)**:
- Creates/updates `service_ops.workflow_instance`
- Links workflow_instance_id to send_integration record

**Issue**: Current implementation doesn't track workflow instances.

### 5. Payload Structure

**Current (ServiceOps Backend)**:
```json
{
  "message_type": "ESMD_PAYLOAD",
  "decision_tracking_id": "...",
  "decision_type": "DIRECT_PA",
  "decision_outcome": "AFFIRM",
  "part_type": "B",
  "is_direct_pa": true,
  "esmd_payload": { ... },
  "attempt_count": 1,
  "payload_hash": "...",
  "payload_version": 1,
  "correlation_id": "...",
  "created_at": "...",
  "created_by": "SYSTEM"
}
```

**New (PA JSON Generator)**:
```json
{
  "decision_tracking_id": "...",
  "message_type": "PA",  // or "UTN"
  "payload_type": "PA",  // or "DECISION_LETTER"
  "header": { ... },
  "procedures": [ ... ],
  "medicalDocuments": [ ... ]
}
```

**Issue**: Different payload structures! Current wraps ESMD payload, new has flat structure.

### 6. Message Status

**Current (ServiceOps Backend)**:
- Sets `message_status_id = 1` (INGESTED)
- Integration service polls and processes

**New (PA JSON Generator)**:
- Sets `message_status_id = 3` (SENT)
- Assumes already processed?

**Issue**: Different status values may cause confusion.

---

## Integration Options

### Option 1: Replace Current Implementation (Recommended)

**Approach**: Remove ESMD payload generation from ServiceOps backend, call PA JSON Generator service instead.

**Changes Required**:
1. Remove `EsmdPayloadGenerator.generate_payload()` call from `ClinicalOpsInboxProcessor`
2. Add HTTP client to call PA JSON Generator endpoint
3. Call `POST /decision/generate_payload_json` with `decision_tracking_id`
4. PA JSON Generator handles all payload generation and writes to `send_integration`

**Pros**:
- Single source of truth for payload generation
- Centralized logic in PA JSON Generator
- Consistent payload structure
- Workflow instance tracking

**Cons**:
- Requires `integration.send_serviceops` to have correct `message_type_id`
- Depends on DDMS database for decision status (may not match ClinicalOps decision)
- Adds external service dependency
- Requires network call (latency, failure handling)

**Data Flow**:
```
ClinicalOps → service_ops.send_serviceops (CLINICAL_DECISION)
     ↓
ClinicalOpsInboxProcessor reads decision
     ↓
Calls PA JSON Generator API: POST /decision/generate_payload_json
     ↓
PA JSON Generator:
  - Reads integration.send_serviceops (for message_type_id)
  - Reads DDMS claim (for decision status)
  - Generates payload
  - Writes to service_ops.send_integration
     ↓
ServiceOps continues workflow (UTN, letter generation, etc.)
```

### Option 2: Keep Both (Fallback)

**Approach**: Try PA JSON Generator first, fallback to current implementation if it fails.

**Changes Required**:
1. Add HTTP client to call PA JSON Generator
2. Try calling PA JSON Generator endpoint
3. If successful, skip current payload generation
4. If fails, use current `EsmdPayloadGenerator` as fallback

**Pros**:
- Resilient to PA JSON Generator failures
- Gradual migration path
- Can compare outputs

**Cons**:
- Duplicate logic
- Two different payload structures
- Complex error handling
- May cause confusion

### Option 3: Hybrid Approach

**Approach**: Use PA JSON Generator for payload generation, but keep current logic for data extraction and workflow.

**Changes Required**:
1. Extract decision data from ClinicalOps payload (current logic)
2. Call PA JSON Generator with extracted data
3. PA JSON Generator generates payload
4. ServiceOps writes to `send_integration` with current structure

**Pros**:
- Uses ClinicalOps decision (not DDMS)
- Keeps current payload structure
- Leverages PA JSON Generator logic

**Cons**:
- Requires PA JSON Generator to accept additional parameters
- May need to modify PA JSON Generator API

---

## Critical Questions to Answer

### 1. Which Table Does ClinicalOps Write To?

**Question**: Does ClinicalOps write to:
- `service_ops.send_serviceops` (current inbox)?
- `integration.send_serviceops` (for message_type_id)?
- Both?

**Impact**: PA JSON Generator requires `integration.send_serviceops` to have `message_type_id` set.

### 2. Decision Source of Truth

**Question**: Which is the source of truth for decision?
- ClinicalOps payload (`decision_outcome: "AFFIRM"`)?
- DDMS claim table (`claimStatus: "Approved"`)?

**Impact**: If they differ, which one should be used for ESMD payload?

### 3. Message Type ID

**Question**: How is `message_type_id` set in `integration.send_serviceops`?
- Is it set when ClinicalOps writes the decision?
- Is it set by another service?
- Does it need to be set before calling PA JSON Generator?

**Impact**: PA JSON Generator will fail if `message_type_id` is NULL.

### 4. Payload Structure Compatibility

**Question**: Can Integration service handle both payload structures?
- Current: Wrapped structure with `esmd_payload` nested
- New: Flat structure with `header`, `procedures`, etc.

**Impact**: May need to update Integration service to handle both formats.

### 5. Workflow Instance

**Question**: Is workflow instance tracking required?
- Current: Not used
- New: PA JSON Generator creates workflow_instance

**Impact**: May need to update ServiceOps to use workflow_instance_id.

---

## Recommended Integration Approach

### Phase 1: Analysis & Preparation

1. **Verify Data Flow**:
   - Confirm ClinicalOps writes to both `service_ops.send_serviceops` AND `integration.send_serviceops`
   - Verify `integration.send_serviceops.message_type_id` is set correctly
   - Verify DDMS claim table has correct decision status

2. **Compare Payloads**:
   - Generate payload using current implementation
   - Generate payload using PA JSON Generator
   - Compare structures and identify differences
   - Verify Integration service can handle both

3. **Test PA JSON Generator**:
   - Call endpoint with test `decision_tracking_id`
   - Verify payload generation works
   - Verify writes to `send_integration` correctly
   - Check workflow_instance creation

### Phase 2: Integration (Option 1 - Replace)

1. **Add HTTP Client**:
   - Create service to call PA JSON Generator API
   - Add retry logic and error handling
   - Add timeout configuration

2. **Modify ClinicalOpsInboxProcessor**:
   - Remove `EsmdPayloadGenerator.generate_payload()` call
   - Add call to PA JSON Generator endpoint
   - Handle response and errors
   - Update packet_decision with ESMD tracking info

3. **Update Error Handling**:
   - Handle PA JSON Generator failures
   - Log errors appropriately
   - Update status if payload generation fails

4. **Update Status Management**:
   - Ensure status updates work with new flow
   - Update packet.detailed_status correctly
   - Handle UTN workflow after payload generation

### Phase 3: Testing

1. **Unit Tests**:
   - Test HTTP client calls
   - Test error handling
   - Test status updates

2. **Integration Tests**:
   - Test end-to-end flow with PA JSON Generator
   - Test with both AFFIRM and NON_AFFIRM decisions
   - Test with Direct PA and Standard PA
   - Test error scenarios

3. **End-to-End Tests**:
   - Test complete workflow: Decision → Payload → UTN → Letter
   - Verify payload structure matches expectations
   - Verify Integration service can process payloads

---

## Code Changes Required (Option 1)

### 1. Add PA JSON Generator Client

**New File**: `wiser-service-operations-backend/app/services/pa_json_generator_client.py`

```python
class PAJsonGeneratorClient:
    async def generate_payload_json(self, decision_tracking_id: str) -> Dict[str, Any]:
        # HTTP call to PA JSON Generator service
        # POST /decision/generate_payload_json
        # Request: { "decision_tracking_id": "..." }
        # Returns: Generated payload result
```

### 2. Modify ClinicalOpsInboxProcessor

**File**: `wiser-service-operations-backend/app/services/clinical_ops_inbox_processor.py`

**Changes**:
- Remove `EsmdPayloadGenerator` import and usage
- Add `PAJsonGeneratorClient` import
- Replace payload generation logic with HTTP call
- Handle response and update packet_decision accordingly

**Location**: `_handle_clinical_decision()` method, around line 324-400

### 3. Configuration

**File**: `wiser-service-operations-backend/app/config/settings.py`

**Add**:
- `PA_JSON_GENERATOR_BASE_URL` - Base URL for PA JSON Generator service
- `PA_JSON_GENERATOR_TIMEOUT` - Request timeout
- `PA_JSON_GENERATOR_RETRY_COUNT` - Retry attempts

---

## Potential Issues & Mitigations

### Issue 1: integration.send_serviceops Missing message_type_id

**Problem**: PA JSON Generator requires `message_type_id` in `integration.send_serviceops`, but it may not be set.

**Mitigation**:
- Verify ClinicalOps writes to `integration.send_serviceops` with `message_type_id`
- Or set `message_type_id` before calling PA JSON Generator
- Or modify PA JSON Generator to determine message_type from decision data

### Issue 2: DDMS Decision Status Mismatch

**Problem**: DDMS claim status may not match ClinicalOps decision.

**Mitigation**:
- Use ClinicalOps decision as source of truth
- Or modify PA JSON Generator to accept decision from request
- Or sync DDMS claim status when ClinicalOps makes decision

### Issue 3: Payload Structure Mismatch

**Problem**: PA JSON Generator creates different payload structure than current implementation.

**Mitigation**:
- Update Integration service to handle both formats
- Or modify PA JSON Generator to match current structure
- Or transform payload after generation

### Issue 4: Network Dependency

**Problem**: PA JSON Generator is external service, adds network dependency.

**Mitigation**:
- Implement retry logic with exponential backoff
- Add circuit breaker pattern
- Have fallback to current implementation (Option 2)
- Monitor service health

### Issue 5: Workflow Instance

**Problem**: PA JSON Generator creates workflow_instance, but current code doesn't use it.

**Mitigation**:
- Update ServiceOps to use workflow_instance_id
- Or ignore workflow_instance if not needed
- Or remove workflow_instance creation from PA JSON Generator

---

## Next Steps

1. **Clarify Data Flow**:
   - Confirm which tables ClinicalOps writes to
   - Verify message_type_id is set correctly
   - Understand DDMS claim status flow

2. **Test PA JSON Generator**:
   - Call endpoint with real decision_tracking_id
   - Verify payload generation
   - Compare with current payload structure

3. **Decide Integration Approach**:
   - Choose Option 1 (Replace), Option 2 (Fallback), or Option 3 (Hybrid)
   - Get stakeholder approval

4. **Implement Changes**:
   - Add HTTP client
   - Modify ClinicalOpsInboxProcessor
   - Update error handling
   - Add configuration

5. **Test Thoroughly**:
   - Unit tests
   - Integration tests
   - End-to-end tests

---

## Summary

**Current State**: ServiceOps backend generates ESMD payloads internally using `EsmdPayloadGenerator`.

**New State**: PA JSON Generator service can generate payloads via HTTP endpoint, using different data sources.

**Key Differences**:
- Different decision source (ClinicalOps payload vs DDMS claim)
- Different table for message_type lookup (`integration.send_serviceops`)
- Different payload structure
- Workflow instance tracking

**Recommendation**: Use **Option 1 (Replace)** after verifying:
1. `integration.send_serviceops` has correct `message_type_id`
2. DDMS claim status matches ClinicalOps decision (or use ClinicalOps as source of truth)
3. Integration service can handle new payload structure
4. PA JSON Generator service is reliable and available

**Risk Level**: Medium - Requires careful testing and coordination between services.

---

**Document Version**: 1.0  
**Last Updated**: 2026-01-14  
**Analysis Type**: End-to-End Code Analysis (No Code Changes)

