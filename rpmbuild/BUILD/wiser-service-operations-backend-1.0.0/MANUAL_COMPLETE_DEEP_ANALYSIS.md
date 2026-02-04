# Manual Complete Functionality - Deep Code Analysis

## Overview
The "Manual Complete" button is a **system override feature** that allows administrators/coordinators to bypass the normal workflow and immediately close a packet that is stuck in clinical review or later stages. This is used when UTN/letters were handled **outside the system** (e.g., manually processed, phone calls, external systems).

---

## When It Appears

### Frontend Visibility (`PacketDetailView.tsx`)
The button only appears when the packet's `detailed_status` is in one of these allowed statuses:

```typescript
const manualCompleteAllowedStatuses = new Set([
  'Pending - Clinical Review',      // ← Your case
  'Clinical Decision Received',
  'Pending - UTN',
  'UTN Received',
  'Generate Decision Letter - Pending',
  'Generate Decision Letter - Complete',
  'Send Decision Letter - Pending',
  'Send Decision Letter - Complete'
]);
```

**Location in UI:** Right side of packet header, grouped with decision dropdown and reason field.

---

## User Flow

1. **User selects decision:** `AFFIRM` or `NON_AFFIRM` from dropdown
2. **User optionally enters reason:** Free-text field for audit trail
3. **User clicks "Manual Complete"** button
4. **Frontend validates:** Ensures decision is selected
5. **API call:** `POST /api/packets/{packet_id}/manual-complete`

---

## Backend API Endpoint

**File:** `app/routes/packets.py` (lines 852-930)

### Authorization
- **Required Roles:** `ADMIN` or `COORDINATOR` only
- **Authentication:** Azure AD SSO token required

### Request Validation
```python
# 1. Validate decision_outcome
if decision_outcome not in {"AFFIRM", "NON_AFFIRM"}:
    raise HTTPException(422, "decision_outcome must be AFFIRM or NON_AFFIRM")

# 2. Validate packet exists
packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()

# 3. Validate packet status is allowed
allowed_statuses = {
    "Pending - Clinical Review",
    "Clinical Decision Received",
    "Pending - UTN",
    "UTN Received",
    "Generate Decision Letter - Pending",
    "Generate Decision Letter - Complete",
    "Send Decision Letter - Pending",
    "Send Decision Letter - Complete",
}
if packet.detailed_status not in allowed_statuses:
    raise HTTPException(409, "Manual completion not allowed for status...")

# 4. Validate document exists
document = db.query(PacketDocumentDB).filter(...).first()
```

---

## Core Service Logic

**File:** `app/services/manual_completion_service.py`

### `ManualCompletionService.complete_packet()`

This service performs **4 major operations** in a single database transaction:

---

### **Step 1: Create Synthetic ClinicalOps Inbox Record**

```python
inbox_record = ClinicalOpsInboxDB(
    decision_tracking_id=packet.decision_tracking_id,
    payload=placeholder_payload,  # System-generated placeholder
    message_status_id=1,
    json_sent_to_integration=None,  # ← KEY: NULL prevents poller from processing
    audit_user="SYSTEM_MANUAL_OVERRIDE",
    audit_timestamp=now,
)
```

**Purpose:** Creates an audit trail record that looks like a ClinicalOps response, but:
- `json_sent_to_integration = NULL` → **Poller ignores it** (won't be processed)
- `source = "SYSTEM_MANUAL_OVERRIDE"` → Clearly marked as synthetic
- Contains placeholder decision data matching the user's selection

**Placeholder Payload Structure:**
```python
{
    "systemGenerated": True,
    "source": "SYSTEM_MANUAL_OVERRIDE",
    "decisionTrackingId": "<uuid>",
    "packetId": "SVC-2026-XXXXXX",
    "decisionOutcome": "AFFIRM" | "NON_AFFIRM",
    "partType": "A" | "B" | "",
    "isDirectPa": True | False,
    "esmdTransactionId": "",
    "procedures": [{
        "procedureCode": "<from packet>",
        "decisionIndicator": "A" | "N",
        "units": "",
        "description": "",
        "diagnosisCodes": []
    }],
    "documentation": [],
    "notes": "<user reason or default>"
}
```

---

### **Step 2: Deactivate Existing Decisions**

```python
existing_decisions = db.query(PacketDecisionDB).filter(
    PacketDecisionDB.packet_id == packet.packet_id,
    PacketDecisionDB.is_active == True,
).all()

for existing in existing_decisions:
    existing.is_active = False  # Mark as superseded
```

**Purpose:** Ensures only one active decision exists per packet. Previous decisions are marked inactive and linked to the new decision via `superseded_by`.

---

### **Step 3: Create New System-Generated Decision Record**

```python
new_decision = PacketDecisionDB(
    packet_id=packet.packet_id,
    packet_document_id=document.packet_document_id,
    decision_type="APPROVE",
    operational_decision="DECISION_COMPLETE",  # ← Final state
    clinical_decision=decision_outcome,  # AFFIRM or NON_AFFIRM
    decision_outcome=decision_outcome,
    is_active=True,
    
    # UTN Fields (synthetic)
    utn="SYSTEM_GENERATED",
    utn_status="SUCCESS",
    utn_received_at=now,
    
    # Letter Fields (synthetic)
    letter_owner="SERVICE_OPS",
    letter_status="SENT",
    letter_package={
        "systemGenerated": True,
        "source": "SYSTEM_MANUAL_OVERRIDE",
        "decisionOutcome": decision_outcome,
        "blobUrl": "",
    },
    letter_generated_at=now,
    letter_sent_to_integration_at=now,
    
    # ESMD Fields (synthetic)
    esmd_request_status="SENT",
    esmd_request_payload={
        "systemGenerated": True,
        "source": "SYSTEM_MANUAL_OVERRIDE",
        "decisionOutcome": decision_outcome,
    },
    
    # Audit
    notes=reason or f"System generated manual completion by {created_by}",
    created_by=created_by,
    correlation_id=str(uuid.uuid4()),
)
```

**Key Fields:**
- `operational_decision = "DECISION_COMPLETE"` → Final workflow state
- `clinical_decision = decision_outcome` → User's AFFIRM/NON_AFFIRM choice
- All UTN/Letter/ESMD fields populated with **synthetic placeholders**
- `supersedes` → Links to previous decision (if exists)

---

### **Step 4: Update Packet Status & Closure Metadata**

```python
# Update status via WorkflowOrchestrator
WorkflowOrchestratorService.update_packet_status(
    db=db,
    packet=packet,
    new_status="Decision Complete",  # ← Final status
    validation_status="Validation Complete",
    release_lock=True,  # ← Unassigns packet (assigned_to = NULL)
)

# Set all completion flags
packet.validation_complete = True
packet.clinical_review_complete = True
packet.delivery_complete = True

# Set closure timestamps
packet.closed_date = now
packet.letter_delivered = now
packet.updated_at = now
```

**What `WorkflowOrchestratorService.update_packet_status()` does:**
```python
packet.detailed_status = "Decision Complete"
packet.validation_status = "Validation Complete"
packet.assigned_to = None  # Release lock
packet.updated_at = now
```

---

## Database Transaction Flow

```
BEGIN TRANSACTION
  ├─ INSERT INTO clinical_ops_inbox (synthetic record)
  ├─ UPDATE packet_decision SET is_active = FALSE (existing decisions)
  ├─ INSERT INTO packet_decision (new synthetic decision)
  ├─ UPDATE packet_decision SET superseded_by = <new_id> (link old decisions)
  ├─ UPDATE packet SET detailed_status = 'Decision Complete'
  │                    validation_status = 'Validation Complete'
  │                    assigned_to = NULL
  │                    validation_complete = TRUE
  │                    clinical_review_complete = TRUE
  │                    delivery_complete = TRUE
  │                    closed_date = NOW()
  │                    letter_delivered = NOW()
  └─ COMMIT
```

**All operations are atomic** - either all succeed or all rollback.

---

## What Gets Created/Updated

### Created Records:
1. **`clinical_ops_inbox`** record (synthetic, not processed by poller)
2. **`packet_decision`** record (system-generated with all synthetic fields)

### Updated Records:
1. **`packet`** table:
   - `detailed_status` → `"Decision Complete"`
   - `validation_status` → `"Validation Complete"`
   - `assigned_to` → `NULL` (released)
   - `validation_complete` → `TRUE`
   - `clinical_review_complete` → `TRUE`
   - `delivery_complete` → `TRUE`
   - `closed_date` → `NOW()`
   - `letter_delivered` → `NOW()`

2. **`packet_decision`** table (existing records):
   - `is_active` → `FALSE`
   - `superseded_by` → `<new_decision_id>`

---

## Audit Trail

### Event Logging
```python
log_packet_event(
    action="manual_complete",
    outcome="success",
    user_id=current_user.id,
    username=current_user.email,
    ip=get_client_ip(request),
    packet_id=packet_id,
    details=f"Manual completion: decision_outcome={decision_outcome}"
)
```

### Synthetic Record Markers
All synthetic records are clearly marked:
- `source = "SYSTEM_MANUAL_OVERRIDE"`
- `systemGenerated = True`
- `audit_user = "SYSTEM_MANUAL_OVERRIDE"` (inbox record)
- `created_by = <user_email>` (decision record)

---

## Why This Exists

### Use Cases:
1. **UTN/Letter handled outside system** - Phone calls, external systems, manual processing
2. **Stuck packets** - Cases where normal workflow failed or was bypassed
3. **Data correction** - Fixing incorrect statuses or completing missing steps
4. **Testing/Development** - Completing test packets without full workflow

### Design Philosophy:
- **Audit trail preserved** - All synthetic records clearly marked
- **Data integrity** - Creates complete decision record with all required fields
- **Workflow bypass** - Skips normal ClinicalOps → UTN → Letter flow
- **Safe closure** - Ensures packet reaches final "Decision Complete" state

---

## Security & Authorization

### Access Control:
- **Role-based:** Only `ADMIN` and `COORDINATOR` roles
- **Authentication:** Azure AD SSO required
- **Status validation:** Only allowed statuses can be manually completed
- **Audit logging:** All actions logged with user, IP, timestamp

### Validation:
- Decision outcome must be `AFFIRM` or `NON_AFFIRM`
- Packet must exist
- Packet must be in allowed status
- Document must exist for packet

---

## Impact on Workflow

### Normal Flow (Bypassed):
```
Pending - Clinical Review
  → Clinical Decision Received
  → Pending - UTN
  → UTN Received
  → Generate Decision Letter - Pending
  → Generate Decision Letter - Complete
  → Send Decision Letter - Pending
  → Send Decision Letter - Complete
  → Decision Complete
```

### Manual Complete Flow:
```
Pending - Clinical Review (or any allowed status)
  → [Manual Complete Button Clicked]
  → Decision Complete (immediate)
```

**All intermediate steps are skipped** and synthetic placeholders are created.

---

## Key Code Files

1. **Frontend:**
   - `wiser-service-operations-mf/src/pages/PacketDetailView.tsx` (lines 207-229, 836-864)

2. **Backend API:**
   - `wiser-service-operations-backend/app/routes/packets.py` (lines 852-930)

3. **Core Service:**
   - `wiser-service-operations-backend/app/services/manual_completion_service.py` (entire file)

4. **Workflow Orchestrator:**
   - `wiser-service-operations-backend/app/services/workflow_orchestrator.py` (lines 24-57)

5. **Models:**
   - `wiser-service-operations-backend/app/models/packet_db.py`
   - `wiser-service-operations-backend/app/models/packet_decision_db.py`
   - `wiser-service-operations-backend/app/models/clinical_ops_db.py`

---

## Testing

**Test File:** `wiser-service-operations-backend/tests/test_manual_completion_service.py`

**Test Coverage:**
- Creates placeholder records correctly
- Deactivates existing decisions
- Updates packet status to "Decision Complete"
- Sets all completion flags
- Marks records as system-generated

---

## Summary

The "Manual Complete" functionality is a **powerful administrative override** that:
1. ✅ Creates synthetic audit records (marked as system-generated)
2. ✅ Deactivates existing decisions and creates new active decision
3. ✅ Updates packet to final "Decision Complete" state
4. ✅ Sets all completion flags and closure timestamps
5. ✅ Releases packet lock (unassigns)
6. ✅ Logs all actions for audit trail
7. ✅ **Skips entire normal workflow** (UTN, Letter generation, etc.)

**Use with caution** - This bypasses normal business processes and should only be used when external systems or manual processes have already completed the required steps.
