# Affirm Button Architecture - Direct Clinical Decision Update

## Overview
Add an "Affirm" button that appears during validation (alongside "Send to Clinical Ops" and "Dismissal"). This button allows ServiceOps to directly update the clinical decision to "AFFIRM" **without creating a send_clinicalops record** and without waiting for the external ClinicalOps system. This provides a shortcut to bypass ClinicalOps entirely.

---

## Current Flow (Before Affirm Button)

```
1. User completes validation
   ↓
2. User has two options:
   - "Send to Clinical Ops" → Creates send_clinicalops record, waits for external system
   - "Dismissal" → Dismissal workflow
   ↓
3. If "Send to Clinical Ops":
   - Creates packet_decision (clinical_decision = "PENDING")
   - Creates send_clinicalops record
   - Status = "Pending - Clinical Review"
   - [WAIT FOR EXTERNAL CLINICALOPS SYSTEM]
   - ClinicalOps processes and sends response
   - Updates clinical_decision = "AFFIRM" or "NON_AFFIRM"
   - Status = "Clinical Decision Received"
```

---

## New Flow (With Affirm Button)

### Option A: Direct Affirm (Bypasses ClinicalOps)

```
1. User completes validation
   ↓
2. User clicks "Affirm" button (shown from start)
   ↓
3. POST /api/decisions/{packet_id}/affirm
   ↓
4. Creates packet_decision with:
   - operational_decision = "PENDING"
   - clinical_decision = "AFFIRM" (directly set)
   - decision_outcome = "AFFIRM"
   ↓
5. Updates packet:
   - detailed_status = "Clinical Decision Received"
   ↓
6. NO send_clinicalops record created (bypassed entirely)
   ↓
7. Workflow continues normally (UTN, Letter generation, etc.)
```

### Option B: Send to Clinical Ops (Normal Flow)

```
1. User completes validation
   ↓
2. User clicks "Send to Clinical Ops" button
   ↓
3. POST /api/decisions/{packet_id}/documents/{doc_id}/decisions/approve
   ↓
4. Creates packet_decision with:
   - operational_decision = "PENDING"
   - clinical_decision = "PENDING"
   ↓
5. Creates send_clinicalops record:
   - message_type = "CASE_READY_FOR_REVIEW"
   - is_picked = NULL
   ↓
6. Updates packet:
   - detailed_status = "Pending - Clinical Review"
   ↓
7. [WAIT FOR EXTERNAL CLINICALOPS SYSTEM]
   ↓
8. ClinicalOps processes and sends response
   ↓
9. Updates clinical_decision = "AFFIRM" or "NON_AFFIRM"
   ↓
10. Status = "Clinical Decision Received"
```

---

## Implementation Plan

### 1. Frontend Changes

**File:** `wiser-service-operations-mf/src/components/DocumentValidationsAndDecision.tsx`

#### Add State:
```typescript
const [isAffirming, setIsAffirming] = useState(false);
```

#### Add Handler:
```typescript
const handleAffirm = async () => {
  try {
    setIsAffirming(true);
    const response = await serviceOpsClient.affirmDecision(packetId);
    if (response.success && response.data) {
      success('Decision affirmed successfully', 'Affirmed');
      // Refresh packet data or navigate
      setTimeout(() => {
        navigate(`/packets/${packetId}`);
      }, 1000);
    } else {
      showError(response.message || 'Failed to affirm decision');
    }
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : 'Failed to affirm decision';
    showError(errorMsg);
    console.error('[DocumentValidationsAndDecision] Affirm error:', err);
  } finally {
    setIsAffirming(false);
  }
};
```

#### Add Button (Show from Start):
```typescript
{/* Show Affirm button alongside "Send to Clinical Ops" and "Dismissal" */}
{/* Show when packet is in validation state (before ClinicalOps) */}
{!denialReason && (
  <div className="flex gap-3">
    <Button
      variant="success"
      onClick={handleApprove}
      fullWidth
    >
      Send to Clinical Ops
    </Button>
    
    <Button
      variant="primary"
      onClick={handleAffirm}
      disabled={isAffirming}
      fullWidth
    >
      {isAffirming ? 'Affirming...' : 'Affirm'}
    </Button>
    
    <Button
      variant="danger"
      onClick={() => setDenialReason('MISSING_FIELDS')}
      fullWidth
    >
      Dismissal
    </Button>
  </div>
)}
```

**Location:** In the Decision section, alongside "Send to Clinical Ops" and "Dismissal" buttons. Shows from the start (during validation phase).

**Current State:** Currently there are **2 buttons** ("Send to Clinical Ops" and "Dismissal")
**New State:** After implementation, there will be **3 buttons**:
1. "Send to Clinical Ops" (existing - green/success variant)
2. "Affirm" (new - primary/blue variant) 
3. "Dismissal" (existing - danger/red variant)

All three buttons will be shown side-by-side in a flex container when `!denialReason` (i.e., during validation phase).

---

### 2. Backend API Endpoint

**File:** `wiser-service-operations-backend/app/routes/decisions.py`

#### New Endpoint:
```python
@router.post(
    "/{packet_id}/affirm",
    response_model=ApiResponse[DecisionResponse],
    status_code=status.HTTP_200_OK
)
async def affirm_decision(
    packet_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Directly affirm a packet's clinical decision without sending to ClinicalOps.
    This bypasses the external ClinicalOps system entirely and immediately sets the decision to AFFIRM.
    No send_clinicalops record is created.
    
    Args:
        packet_id: External packet ID
        
    Returns:
        Updated decision record
    """
    # Validate packet exists
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Validate packet is in correct status (before ClinicalOps)
    # Allow affirm if packet is in validation phase or pending clinical review
    allowed_statuses = {
        "Pending - Validation",
        "Validation In Progress", 
        "Validation Complete",
        "Pending - Clinical Review"  # Also allow if already sent to ClinicalOps
    }
    
    if packet.detailed_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Can only affirm packets in validation or pending clinical review. Current status: '{packet.detailed_status}'"
        )
    
    # Check for existing active decision
    active_decision = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.packet_id == packet.packet_id,
        PacketDecisionDB.is_active == True
    ).first()
    
    # If decision exists, validate it's still PENDING
    if active_decision:
        if active_decision.clinical_decision not in ("PENDING", None):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Clinical decision already set to '{active_decision.clinical_decision}'. Cannot affirm."
            )
    else:
        # No decision exists yet - we'll create one with AFFIRM directly
        # Get document for the packet
        document = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No document found for this packet"
            )
    
    try:
        # If decision exists, update it; otherwise create new one with AFFIRM
        if active_decision:
            # Update existing decision
            updated_decision = DecisionsService.update_clinical_decision(
                db=db,
                packet_id=packet.packet_id,
                new_clinical_decision="AFFIRM",
                decision_outcome="AFFIRM",
                created_by=current_user.email
            )
        else:
            # Create new decision directly with AFFIRM (bypasses ClinicalOps entirely)
            from app.services.decisions_service import DecisionsService
            from app.services.validations_persistence import ValidationsPersistenceService
            
            # Get validation run IDs
            linked_runs = ValidationsPersistenceService.get_last_validation_run_ids(
                db, document.packet_document_id
            )
            
            # Create approve decision with AFFIRM directly
            updated_decision = DecisionsService.create_approve_decision(
                db=db,
                packet_id=packet.packet_id,
                packet_document_id=document.packet_document_id,
                notes=f"Direct affirm by {current_user.email} (bypassed ClinicalOps)",
                created_by=current_user.email
            )
            
            # Immediately update to AFFIRM (bypasses PENDING state)
            updated_decision = DecisionsService.update_clinical_decision(
                db=db,
                packet_id=packet.packet_id,
                new_clinical_decision="AFFIRM",
                decision_outcome="AFFIRM",
                created_by=current_user.email
            )
        
        # Update packet status to "Clinical Decision Received"
        from app.services.workflow_orchestrator import WorkflowOrchestratorService
        
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Clinical Decision Received"
        )
        
        # NOTE: We do NOT create a send_clinicalops record at all
        # This is a direct affirm that bypasses ClinicalOps entirely
        # If a send_clinicalops record exists (from previous "Send to Clinical Ops"), we leave it as-is
        
        db.commit()
        db.refresh(packet)
        db.refresh(updated_decision)
        
        logger.info(
            f"Packet {packet_id} directly affirmed: "
            f"clinical_decision=AFFIRM, "
            f"status=Clinical Decision Received, "
            f"user={current_user.email}"
        )
        
        # Build response
        response_data = DecisionResponse(
            packet_decision_id=updated_decision.packet_decision_id,
            packet_id=packet_id,
            document_id=None,  # Not needed for this response
            decision_type=updated_decision.decision_type,
            denial_reason=None,
            denial_details=None,
            notes=updated_decision.notes,
            linked_validation_run_ids=updated_decision.linked_validation_run_ids,
            created_at=updated_decision.created_at.isoformat(),
            created_by=updated_decision.created_by or current_user.email,
            operational_decision=updated_decision.operational_decision,
            clinical_decision=updated_decision.clinical_decision,
            is_active=updated_decision.is_active
        )
        
        return ApiResponse(
            success=True,
            data=response_data,
            message="Decision affirmed successfully",
            correlation_id=getattr(request.state, 'correlation_id', None)
        )
    
    except Exception as e:
        logger.exception(f"Unexpected error during affirm decision: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during affirm decision"
        )
```

---

### 3. API Client Method

**File:** `wiser-service-operations-mf/src/services/serviceOpsClient.ts` (or similar)

```typescript
affirmDecision: async (packetId: string): Promise<ApiResponse<DecisionResponse>> => {
  const response = await api.post(`/decisions/${packetId}/affirm`);
  return response;
}
```

---

### 4. Database Changes

**No schema changes required** - all necessary fields already exist:
- `packet_decision.clinical_decision` - already exists
- `packet_decision.decision_outcome` - already exists
- `send_clinicalops.is_picked` - already exists (from migration 023)
- `packet.detailed_status` - already exists
- `clinical_ops_inbox` - already exists (for synthetic record)

---

### 5. Service Layer

**File:** `wiser-service-operations-backend/app/services/decisions_service.py`

**No changes needed** - `update_clinical_decision()` method already exists and handles:
- Deactivating current decision
- Creating new decision record with audit trail
- Setting `clinical_decision = "AFFIRM"`
- Setting `decision_outcome = "AFFIRM"`
- Preserving other decision fields

---

### 6. UI Location Options

#### Option A: In Decision Component (DocumentValidationsAndDecision.tsx)
- Shows in the Decision card section
- Appears after "Send to Clinical Ops" is clicked
- Good for workflow continuity

#### Option B: In Packet Detail View (PacketDetailView.tsx)
- Shows in the packet header/status section
- Appears when viewing packet details
- Good for quick actions from packet list

#### Option C: Both Locations
- Show in both places for maximum visibility
- Consistent UX across different views

**Recommendation:** Option A (Decision Component) - keeps the workflow in one place.

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ User completes validation                                   │
│ UI shows 3 buttons: "Send to Clinical Ops", "Affirm", "Dismissal"│
└────────────────────┬──────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
┌───────────────────┐   ┌───────────────────┐
│ User clicks       │   │ User clicks       │
│ "Affirm"          │   │ "Send to Clinical │
│                   │   │ Ops"              │
└─────────┬─────────┘   └─────────┬─────────┘
          │                       │
          ▼                       │
┌───────────────────┐             │
│ POST /decisions/  │             │
│ {packet_id}/affirm│             │
│                   │             │
│ 1. Validates      │             │
│    packet status  │             │
│ 2. Creates/updates│             │
│    decision with  │             │
│    clinical_      │             │
│    decision =     │             │
│    "AFFIRM"       │             │
│ 3. Updates packet │             │
│    status =       │             │
│    "Clinical      │             │
│    Decision       │             │
│    Received"      │             │
│ 4. NO send_       │             │
│    clinicalops    │             │
│    record created │             │
└─────────┬─────────┘             │
          │                       │
          │                       ▼
          │             ┌───────────────────┐
          │             │ POST /decisions/    │
          │             │ {id}/documents/    │
          │             │ {doc_id}/decisions/│
          │             │ approve            │
          │             │                   │
          │             │ 1. Creates        │
          │             │    packet_decision │
          │             │    (PENDING)      │
          │             │ 2. Creates        │
          │             │    send_clinicalops│
          │             │    record         │
          │             │ 3. Status =       │
          │             │    "Pending -     │
          │             │    Clinical       │
          │             │    Review"        │
          │             └─────────┬─────────┘
          │                       │
          │                       │
          └───────────┬───────────┘
                      │
                      ▼
        ┌─────────────────────────────┐
        │ Workflow continues:         │
        │ - Status: "Clinical Decision│
        │   Received" (Affirm)        │
        │   OR                        │
        │   "Pending - Clinical       │
        │   Review" (Send to Clinical)│
        │ - Next: UTN, Letter gen, etc│
        └─────────────────────────────┘
```

---

## Key Design Decisions

### 1. Why NOT Create `send_clinicalops` Record for Affirm?
- **Bypasses ClinicalOps entirely:** Affirm is a direct decision, no need to send to external system
- **Cleaner workflow:** No outbox record needed if we're not actually sending to ClinicalOps
- **Simpler:** Direct path from validation → decision → UTN/Letter workflow
- **User choice:** User explicitly chooses to bypass ClinicalOps by clicking "Affirm" instead of "Send to Clinical Ops"

### 2. When is `send_clinicalops` Record Created?
- **Only when "Send to Clinical Ops" is clicked:** Normal flow creates the record
- **Not created for "Affirm":** Direct affirm bypasses this entirely
- **If record exists and user affirms later:** We leave it as-is (no update needed)

### 3. Why Use `DecisionsService.update_clinical_decision()`?
- **Reuses existing logic:** No code duplication
- **Audit trail:** Creates new decision record (proper audit chain)
- **Race condition protection:** Uses `with_for_update()` for safety
- **Consistency:** Same pattern as normal ClinicalOps flow

### 4. Status Validation
- **Flexible check:** Allows affirming during validation phase OR if already sent to ClinicalOps
- **Allowed statuses:** "Pending - Validation", "Validation In Progress", "Validation Complete", "Pending - Clinical Review"
- **Prevents misuse:** Can't affirm if clinical decision already set to AFFIRM/NON_AFFIRM
- **Idempotency:** If already affirmed, returns success without error

---

## Security & Authorization

### Access Control:
- **Authentication:** Azure AD SSO required (same as approve endpoint)
- **Role-based:** Should use same roles as approve (likely `COORDINATOR` or `ADMIN`)
- **Audit logging:** All actions logged with user, IP, timestamp

### Validation:
- Packet must exist
- Packet must be in validation phase or "Pending - Clinical Review" status
- If decision exists, clinical decision must be "PENDING" (not already set)
- If no decision exists, one will be created with AFFIRM directly

---

## Error Handling

### Possible Errors:
1. **Packet not found** → 404
2. **Wrong status** → 409 Conflict
3. **No active decision** → 404
4. **Clinical decision already set** → 409 Conflict
5. **Database error** → 500 with rollback

### Idempotency:
- If clinical_decision is already "AFFIRM", return success (idempotent)
- If status is already "Clinical Decision Received", return success

---

## Testing Considerations

### Unit Tests:
1. Test successful affirm flow (no decision exists - creates new with AFFIRM)
2. Test successful affirm flow (decision exists - updates to AFFIRM)
3. Test validation errors (wrong status, decision already set, etc.)
4. Test idempotency (calling twice)
5. Test that NO send_clinicalops record is created
6. Test that workflow continues normally after affirm

### Integration Tests:
1. Test full flow: Validation → Affirm → Status = "Clinical Decision Received"
2. Test full flow: Validation → Send to Clinical Ops → Status = "Pending - Clinical Review"
3. Test that affirm bypasses ClinicalOps entirely (no send_clinicalops record)
4. Test that normal "Send to Clinical Ops" flow still works correctly

---

## Files to Modify

### Frontend:
1. `wiser-service-operations-mf/src/components/DocumentValidationsAndDecision.tsx`
   - Add state for `isAffirming`
   - Add `handleAffirm` function
   - Add "Affirm" button (conditional rendering)

2. `wiser-service-operations-mf/src/services/serviceOpsClient.ts` (or similar)
   - Add `affirmDecision` method

### Backend:
1. `wiser-service-operations-backend/app/routes/decisions.py`
   - Add new `affirm_decision` endpoint

2. **No service changes needed** - `DecisionsService.update_clinical_decision()` already exists

3. **No model changes needed** - all fields exist

---

## Implementation Notes

### No Records Created for Affirm
- **No `send_clinicalops` record created:** Affirm bypasses ClinicalOps entirely
- **No `clinical_ops_inbox` record:** Not needed for this flow
- **Only creates/updates:** Decision record with `clinical_decision = "AFFIRM"` directly

### What Gets Created/Updated
1. **packet_decision:** 
   - If no decision exists: Creates new with `clinical_decision = "AFFIRM"` directly
   - If decision exists: Updates to `clinical_decision = "AFFIRM"` (new record for audit)
2. **packet:** Status updated to "Clinical Decision Received"
3. **send_clinicalops:** NOT created (bypassed entirely)

---

## Summary

This feature allows ServiceOps to directly affirm a decision **without sending to ClinicalOps at all**. It:

1. ✅ Shows "Affirm" button from the start (alongside "Send to Clinical Ops")
2. ✅ Creates decision with `clinical_decision = "AFFIRM"` directly (no PENDING state)
3. ✅ Updates status to "Clinical Decision Received" immediately
4. ✅ **Does NOT create send_clinicalops record** (bypasses ClinicalOps entirely)
5. ✅ Reuses existing service methods (no code duplication)
6. ✅ Continues normal workflow (UTN, Letter generation, etc.)
7. ✅ Provides user choice: Affirm directly OR send to ClinicalOps

**Key Point:** This is a **direct affirm path** that completely bypasses the ClinicalOps external system. No outbox record is created. Users can choose between:
- **"Affirm"** → Direct decision, no ClinicalOps involvement
- **"Send to Clinical Ops"** → Normal flow, sends to external system
