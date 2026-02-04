# Status Determination Plan - Using New Decision Fields

## Overview
After migrating old records to populate `operational_decision` and `clinical_decision`, all status calculations will use these new fields instead of parsing `detailed_status` strings.

---

## Status Determination Table

| UI Status | Conditions (ALL must be true) | SQL Logic |
|-----------|------------------------------|-----------|
| **Intake Validation** | • `pd.operational_decision = 'PENDING'` OR `pd IS NULL`<br>• `pd.clinical_decision = 'PENDING'` OR `pd IS NULL`<br>• No record in `send_clinicalops` with `CASE_READY_FOR_REVIEW` | `LEFT JOIN packet_decision pd ON p.packet_id = pd.packet_id AND pd.is_active = true`<br>`LEFT JOIN send_clinicalops sco ON p.decision_tracking_id = sco.decision_tracking_id AND sco.payload->>'message_type' = 'CASE_READY_FOR_REVIEW' AND sco.is_deleted = false`<br>`WHERE (pd.operational_decision = 'PENDING' OR pd IS NULL)`<br>`AND (pd.clinical_decision = 'PENDING' OR pd IS NULL)`<br>`AND sco.message_id IS NULL` |
| **Clinical Review** | • `pd.operational_decision = 'PENDING'`<br>• `pd.clinical_decision = 'PENDING'`<br>• EXISTS record in `send_clinicalops` with `CASE_READY_FOR_REVIEW`<br>• `pd.clinical_decision` NOT IN ('AFFIRM', 'NON_AFFIRM') | `LEFT JOIN packet_decision pd ON p.packet_id = pd.packet_id AND pd.is_active = true`<br>`INNER JOIN send_clinicalops sco ON p.decision_tracking_id = sco.decision_tracking_id AND sco.payload->>'message_type' = 'CASE_READY_FOR_REVIEW' AND sco.is_deleted = false`<br>`WHERE pd.operational_decision = 'PENDING'`<br>`AND pd.clinical_decision = 'PENDING'` |
| **UTN Outbound** | • `pd.operational_decision = 'PENDING'`<br>• `pd.clinical_decision IN ('AFFIRM', 'NON_AFFIRM')`<br>• `pd.utn_status IS NULL OR pd.utn_status = 'NONE' OR pd.utn_status = 'FAILED'` | `LEFT JOIN packet_decision pd ON p.packet_id = pd.packet_id AND pd.is_active = true`<br>`WHERE pd.operational_decision = 'PENDING'`<br>`AND pd.clinical_decision IN ('AFFIRM', 'NON_AFFIRM')`<br>`AND (pd.utn_status IS NULL OR pd.utn_status = 'NONE' OR pd.utn_status = 'FAILED')` |
| **Letter Outbound** | • `pd.operational_decision = 'PENDING'`<br>• `pd.clinical_decision IN ('AFFIRM', 'NON_AFFIRM')`<br>• `pd.utn_status = 'SUCCESS'`<br>• `pd.letter_status IS NULL OR pd.letter_status IN ('NONE', 'PENDING', 'READY')` | `LEFT JOIN packet_decision pd ON p.packet_id = pd.packet_id AND pd.is_active = true`<br>`WHERE pd.operational_decision = 'PENDING'`<br>`AND pd.clinical_decision IN ('AFFIRM', 'NON_AFFIRM')`<br>`AND pd.utn_status = 'SUCCESS'`<br>`AND (pd.letter_status IS NULL OR pd.letter_status IN ('NONE', 'PENDING', 'READY'))` |
| **Decision Complete** | • `pd.operational_decision = 'DECISION_COMPLETE'` | `LEFT JOIN packet_decision pd ON p.packet_id = pd.packet_id AND pd.is_active = true`<br>`WHERE pd.operational_decision = 'DECISION_COMPLETE'` |
| **Dismissal Complete** | • `pd.operational_decision = 'DISMISSAL_COMPLETE'` | `LEFT JOIN packet_decision pd ON p.packet_id = pd.packet_id AND pd.is_active = true`<br>`WHERE pd.operational_decision = 'DISMISSAL_COMPLETE'` |

---

## Priority Order (for packets matching multiple conditions)

Statuses are mutually exclusive. Evaluation order:

1. **Dismissal Complete** (highest priority - final state)
2. **Decision Complete** (highest priority - final state)
3. **Letter Outbound** (requires UTN success)
4. **UTN Outbound** (requires clinical decision)
5. **Clinical Review** (requires sent to clinical)
6. **Intake Validation** (default/catch-all)

---

## Backend Implementation Plan

### Step 1: Update Status Counts Query

**File:** `app/routes/packets.py` (around line 254)

**Current Approach:**
- Uses `detailed_status` string matching with `CASE` statements
- Multiple `LIKE` patterns for backward compatibility

**New Approach:**
```python
# Base query with LEFT JOIN to packet_decision
base_query_for_counts = db.query(PacketDB).outerjoin(
    PacketDecisionDB,
    and_(
        PacketDB.packet_id == PacketDecisionDB.packet_id,
        PacketDecisionDB.is_active == True
    )
).outerjoin(
    SendClinicalOpsDB,
    and_(
        PacketDB.decision_tracking_id == SendClinicalOpsDB.decision_tracking_id,
        SendClinicalOpsDB.payload['message_type'].astext == 'CASE_READY_FOR_REVIEW',
        SendClinicalOpsDB.is_deleted == False
    )
)

# Status counts using new fields
status_counts_query = base_query_for_counts.with_entities(
    func.count(PacketDB.packet_id).label('total_count'),
    
    # Intake Validation
    func.sum(case((
        and_(
            or_(PacketDecisionDB.operational_decision == 'PENDING', PacketDecisionDB.packet_decision_id.is_(None)),
            or_(PacketDecisionDB.clinical_decision == 'PENDING', PacketDecisionDB.packet_decision_id.is_(None)),
            SendClinicalOpsDB.message_id.is_(None)
        ), 1
    ), else_=0)).label('intake_validation'),
    
    # Clinical Review
    func.sum(case((
        and_(
            PacketDecisionDB.operational_decision == 'PENDING',
            PacketDecisionDB.clinical_decision == 'PENDING',
            SendClinicalOpsDB.message_id.isnot(None)
        ), 1
    ), else_=0)).label('clinical_review'),
    
    # UTN Outbound
    func.sum(case((
        and_(
            PacketDecisionDB.operational_decision == 'PENDING',
            PacketDecisionDB.clinical_decision.in_(['AFFIRM', 'NON_AFFIRM']),
            or_(
                PacketDecisionDB.utn_status.is_(None),
                PacketDecisionDB.utn_status == 'NONE',
                PacketDecisionDB.utn_status == 'FAILED'
            )
        ), 1
    ), else_=0)).label('utn_outbound'),
    
    # Letter Outbound
    func.sum(case((
        and_(
            PacketDecisionDB.operational_decision == 'PENDING',
            PacketDecisionDB.clinical_decision.in_(['AFFIRM', 'NON_AFFIRM']),
            PacketDecisionDB.utn_status == 'SUCCESS',
            or_(
                PacketDecisionDB.letter_status.is_(None),
                PacketDecisionDB.letter_status.in_(['NONE', 'PENDING', 'READY'])
            )
        ), 1
    ), else_=0)).label('letter_outbound'),
    
    # Decision Complete
    func.sum(case((
        PacketDecisionDB.operational_decision == 'DECISION_COMPLETE', 1
    ), else_=0)).label('decision_complete'),
    
    # Dismissal Complete
    func.sum(case((
        PacketDecisionDB.operational_decision == 'DISMISSAL_COMPLETE', 1
    ), else_=0)).label('dismissal_complete'),
)
```

### Step 2: Update Packet Filtering Logic

**File:** `app/routes/packets.py` (around line 200-250)

**Current Approach:**
- Filters by `detailed_status` using string matching

**New Approach:**
- Add similar JOINs to main query
- Filter using `operational_decision`, `clinical_decision`, `utn_status`, `letter_status`
- Keep `detailed_status` filter as fallback for edge cases

### Step 3: Update High-Level Status Mapping

**File:** `app/utils/packet_converter.py` (if exists)

**Current Approach:**
- Derives `high_level_status` from `detailed_status` string

**New Approach:**
- Derive from `operational_decision` + `clinical_decision` + `utn_status` + `letter_status`
- Use same logic as status counts query

---

## Frontend Implementation

### Current State
- Frontend receives `status_counts` object from backend
- Displays counts in dashboard cards
- Filters packets by `high_level_status` or `detailed_status`

### After Migration
- **No changes needed** - Frontend continues to receive same `status_counts` object
- Backend calculates counts using new fields
- Frontend filtering still works (backend handles the translation)

---

## Migration Impact

### Old Records (After Migration)
- All old records will have `operational_decision` and `clinical_decision` populated
- They will be counted using the same logic as new records
- No special handling needed

### New Records
- Already use new fields
- No changes needed

### Edge Cases Handled
1. **Packets without decisions:** Counted as "Intake Validation"
2. **UTN failures:** Still counted as "UTN Outbound" (retry pending)
3. **Letter generation in progress:** Counted as "Letter Outbound"
4. **Multiple active decisions:** Only `is_active = true` decision is used

---

## Testing Checklist

- [ ] Verify status counts match expected values after migration
- [ ] Test packets in each status category
- [ ] Verify edge cases (no decision, UTN failure, etc.)
- [ ] Test filtering by status in UI
- [ ] Verify dashboard displays correct counts
- [ ] Test with old migrated records
- [ ] Test with new records
- [ ] Verify no packets are counted in multiple statuses

---

## Benefits

1. **Single Source of Truth:** All status logic uses decision fields
2. **Accurate Counts:** No string parsing, uses structured data
3. **Consistent:** Old and new records use same logic
4. **Maintainable:** Clear, explicit conditions
5. **Future-Proof:** New records already use this approach



