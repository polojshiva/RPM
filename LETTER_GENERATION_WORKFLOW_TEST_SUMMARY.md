# Letter Generation Workflow End-to-End Test Summary

**Date:** 2026-01-15  
**Purpose:** Test the complete letter generation workflow from UTN received to letter generation for AFFIRM, NON_AFFIRM, and DISMISSAL decisions

## Test Script

**File:** `scripts/test_letter_generation_workflow.py`

## Test Scenarios

### Test 1: AFFIRM Decision Workflow

**Flow:**
1. Create synthetic packet, document, and decision with `decision_outcome = "AFFIRM"`
2. Simulate UTN_SUCCESS message received
3. `UtnSuccessHandler.handle()` processes UTN
4. Verifies:
   - UTN is stored in `packet_decision.utn`
   - `utn_status = "SUCCESS"`
   - Letter generation is triggered automatically
   - `letter_status = "READY"`
   - `letter_package` contains blob URL
   - Packet status updated to "Decision Complete"
   - Operational decision updated to "DECISION_COMPLETE"

**Expected Result:**
- Letter generated successfully via LetterGen API
- All database fields updated correctly
- Letter sent to `service_ops.send_integration` outbox

### Test 2: NON_AFFIRM Decision Workflow

**Flow:**
1. Create synthetic packet, document, and decision with `decision_outcome = "NON_AFFIRM"`
2. Add review codes and program codes to decision
3. Simulate UTN_SUCCESS message received
4. `UtnSuccessHandler.handle()` processes UTN
5. Verifies:
   - UTN is stored
   - Letter generation triggered
   - Non-affirmation letter generated with review/program codes
   - Status updated correctly

**Expected Result:**
- Non-affirmation letter generated successfully
- Review codes and program codes included in letter payload

### Test 3: DISMISSAL Decision Workflow

**Flow:**
1. Create synthetic packet and document
2. Create dismissal decision with `decision_outcome = "DISMISSAL"`
3. Call `DismissalWorkflowService.process_dismissal()`
4. Verifies:
   - Letter generated immediately (no UTN required)
   - `letter_status = "READY"` or `"SENT"`
   - Packet status updated to "Dismissal Complete"
   - Operational decision updated to "DISMISSAL_COMPLETE"
   - No ESMD payload generated (dismissals don't go to ESMD)

**Expected Result:**
- Dismissal letter generated successfully
- Workflow completes without UTN
- Status updated to "Dismissal Complete"

### Test 4: Direct LetterGenerationService Test

**Flow:**
1. Create synthetic packet, document, and decision
2. Call `LetterGenerationService.generate_letter()` directly
3. Verifies:
   - LetterGen API is called correctly
   - Response contains blob URL
   - Letter metadata stored correctly

**Expected Result:**
- Direct service call works
- Letter generated and metadata returned

## Workflow Logic

### AFFIRM/NON_AFFIRM Flow

```
1. Decision Received (from ClinicalOps)
   ↓
2. packet_decision.decision_outcome = "AFFIRM" or "NON_AFFIRM"
   ↓
3. packet.detailed_status = "Pending - UTN"
   ↓
4. UTN_SUCCESS Message Received
   ↓
5. UtnSuccessHandler.handle()
   - Updates packet_decision.utn
   - Updates packet_decision.utn_status = "SUCCESS"
   - Updates packet.detailed_status = "UTN Received"
   ↓
6. Checks if decision_outcome in ['AFFIRM', 'NON_AFFIRM']
   ↓
7. Triggers LetterGenerationService.generate_letter()
   ↓
8. Letter Generated
   - packet_decision.letter_status = "READY"
   - packet_decision.letter_package = {blob_url, filename, ...}
   - packet.detailed_status = "Generate Decision Letter - Complete"
   ↓
9. Letter Sent to Integration
   - Creates record in service_ops.send_integration
   - packet_decision.letter_status = "SENT"
   - packet.detailed_status = "Send Decision Letter - Complete"
   ↓
10. Final Status Update
    - packet.detailed_status = "Decision Complete"
    - packet_decision.operational_decision = "DECISION_COMPLETE"
```

### DISMISSAL Flow

```
1. User Clicks Dismissal
   ↓
2. DismissalWorkflowService.process_dismissal()
   ↓
3. Letter Generated Immediately (no UTN required)
   - packet_decision.letter_status = "READY"
   - packet_decision.letter_package = {blob_url, filename, ...}
   - packet.detailed_status = "Generate Decision Letter - Complete"
   ↓
4. Letter Sent to Integration
   - Creates record in service_ops.send_integration
   - packet_decision.letter_status = "SENT"
   - packet.detailed_status = "Send Decision Letter - Complete"
   ↓
5. Final Status Update
   - packet.detailed_status = "Dismissal Complete"
   - packet_decision.operational_decision = "DISMISSAL_COMPLETE"
```

## Key Components Tested

1. **UtnSuccessHandler** (`app/services/utn_handlers.py`)
   - Handles UTN_SUCCESS messages
   - Triggers letter generation for AFFIRM/NON_AFFIRM
   - Updates packet and decision status

2. **LetterGenerationService** (`app/services/letter_generation_service.py`)
   - Calls LetterGen API
   - Builds correct payload for each letter type
   - Handles retries and errors

3. **DismissalWorkflowService** (`app/services/dismissal_workflow_service.py`)
   - Processes dismissal decisions
   - Generates dismissal letters
   - Updates status correctly

4. **WorkflowOrchestratorService** (`app/services/workflow_orchestrator.py`)
   - Updates packet status throughout workflow
   - Manages status transitions

## Prerequisites

1. **Database:** PostgreSQL with ServiceOps schema
2. **LetterGen API:** Configured via `LETTERGEN_BASE_URL` environment variable
3. **Test Data:** Script creates synthetic records (cleaned up after test)

## Running the Test

```bash
cd wiser-service-operations-backend
python scripts/test_letter_generation_workflow.py
```

## Expected Output

```
================================================================================
Letter Generation Workflow End-to-End Test
================================================================================
Test Date: 2026-01-15T13:XX:XX
LetterGen Base URL: https://dev-wiser-letter-generatorv2.azurewebsites.net

================================================================================
TEST 1: AFFIRM Decision Workflow
================================================================================
[PASS] Create Test Records - Created packet_id=X, decision_id=Y
[PASS] UTN Received - UTN=UTN123456789, status=SUCCESS
[PASS] Letter Generated - Letter status=READY
[PASS] Letter Package - Blob URL: https://...
[PASS] Packet Status - Status=Decision Complete
[PASS] Operational Decision - Decision=DECISION_COMPLETE
[PASS] Cleanup - Test records deleted

================================================================================
TEST 2: NON_AFFIRM Decision Workflow
================================================================================
[PASS] Create Test Records - Created packet_id=X, decision_id=Y
[PASS] UTN Received - UTN=UTN987654321, status=SUCCESS
[PASS] Letter Generated - Letter status=READY
[PASS] Letter Package - Blob URL: https://...
[PASS] Packet Status - Status=Decision Complete
[PASS] Cleanup - Test records deleted

================================================================================
TEST 3: DISMISSAL Decision Workflow
================================================================================
[PASS] Create Test Records - Created packet_id=X, decision_id=Y
[PASS] Letter Generated - Letter status=READY
[PASS] Letter Package - Letter metadata present
[PASS] Packet Status - Status=Dismissal Complete
[PASS] Operational Decision - Decision=DISMISSAL_COMPLETE
[PASS] Cleanup - Test records deleted

================================================================================
TEST 4: Direct LetterGenerationService Test
================================================================================
[PASS] Create Test Records - Created packet_id=X
[PASS] Letter Generation - Generated letter: affirmation_...
[PASS] Letter Blob URL - URL: https://...
[PASS] Cleanup - Test records deleted

================================================================================
TEST SUMMARY
================================================================================
Total Tests: 20+
Passed: 20+
Failed: 0
```

## Integration Points

1. **LetterGen API:** 
   - Endpoints: `/api/v2/affirmation`, `/api/v2/non-affirmation`, `/api/v2/dismissal`
   - Payload structure matches API contract
   - Response contains blob URL and metadata

2. **Database Updates:**
   - `packet_decision.utn` - UTN number
   - `packet_decision.utn_status` - SUCCESS/FAILED
   - `packet_decision.letter_status` - READY/SENT/FAILED
   - `packet_decision.letter_package` - Full letter metadata
   - `packet.detailed_status` - Workflow status
   - `packet_decision.operational_decision` - Final decision status

3. **Integration Outbox:**
   - `service_ops.send_integration` - Letter package sent to Integration layer
   - Message type: `LETTER_PACKAGE`
   - Contains letter blob URL and metadata

## Notes

- Test creates synthetic records that are cleaned up after each test
- If LetterGen API is not configured, tests will fail with appropriate error messages
- All database transactions are rolled back on error
- Test verifies both the workflow logic and actual API integration



