# Bulletproof Clinical Ops Decision Workflow

## Overview

This document describes the comprehensive fix to make the Clinical Ops decision workflow 100% reliable and bug-free. The fix addresses all known failure modes and ensures decisions are always applied to `packet_decision` even when downstream steps (JSON Generator, letter generation) fail.

## Problem Statement

### Original Issues

1. **Watermark skips failed messages**: If message 825 fails, watermark advances to 827 → message 825 is never retried
2. **Phase 2 rows never get decision applied**: Rows with `json_sent_to_integration = true` but decision never written → processor only runs Phase 2, never writes to `packet_decision`
3. **Duplicate processing**: Multiple app instances can process the same message
4. **No per-row "applied" state**: Cannot reliably know if a decision has been written without scanning `packet_decision`
5. **Tight coupling**: Phase 1 (decision write) tied to Phase 2 (JSON Generator) in one flow

## Solution

### Core Principle

**Single responsibility**: One job = "For every row in `send_serviceops` that has a valid decision (A/N) in the JSON column, ensure `packet_decision` has that decision." Do this in a simple, linear way. Treat JSON Generator / letter as separate, best-effort steps.

### Key Changes

#### 1. Database Migration (030)

**File**: `deploy/migrations/030_add_clinical_decision_applied_at.sql`

- Adds `clinical_decision_applied_at TIMESTAMPTZ NULL` column to `service_ops.send_serviceops`
- Creates index for faster queries on unapplied decisions
- Backfills existing Phase 2 rows (sets `clinical_decision_applied_at = created_at`)

**Why**: Provides a single source of truth per row: "has this message's decision been written to `packet_decision`?"

#### 2. Updated Poll Query

**File**: `app/services/clinical_ops_inbox_processor.py` → `_poll_new_messages()`

**Changes**:
- Filters by `clinical_decision_applied_at IS NULL` (only unapplied decisions)
- Filters by `clinical_ops_decision_json->>'decision_indicator' IN ('A', 'N')` (only valid decisions)
- Uses `FOR UPDATE SKIP LOCKED` for row-level locking (prevents duplicate processing)

**Why**: Only processes rows that still need the decision written. Retries are natural: if we didn't set `clinical_decision_applied_at` (e.g. we failed before commit), the row stays in the poll.

#### 3. Always Apply Decision First

**File**: `app/services/clinical_ops_inbox_processor.py` → `_process_message()`

**Changes**:
- **ALWAYS** applies decision if `clinical_ops_decision_json` has A/N (even for Phase 2 rows)
- Idempotent: if decision already applied, skips update
- Sets `clinical_decision_applied_at` after successful commit
- Then handles Phase 2 (JSON Generator, payload processing) as best-effort

**Why**: Ensures decision is written even if Phase 1 was skipped. One code path for "apply decision from JSON."

#### 4. Watermark Only Advances on Consecutive Successes

**File**: `app/services/clinical_ops_inbox_processor.py` → `_poll_and_process()`

**Changes**:
- Tracks `first_failure_idx` in batch
- Only advances watermark to last consecutive success (stops at first failure)
- Failed messages remain in poll for retry

**Why**: Prevents watermark from skipping failed messages. Failed messages are retried automatically.

#### 5. Row-Level Locking

**File**: `app/services/clinical_ops_inbox_processor.py` → `_poll_new_messages()`

**Changes**:
- Added `FOR UPDATE SKIP LOCKED` to poll query

**Why**: Prevents duplicate processing when multiple app instances run. Only the instance that locks the row processes it.

## Migration Steps

### Step 1: Run Migration

```bash
cd wiser-service-operations-backend
python scripts/run_migration_030.py
```

This will:
- Add `clinical_decision_applied_at` column
- Create index for faster queries
- Backfill existing Phase 2 rows

### Step 2: Deploy Code

Deploy the updated `clinical_ops_inbox_processor.py` code. The processor will:
- Only poll for unapplied decisions (`clinical_decision_applied_at IS NULL`)
- Always apply decision first (even for Phase 2 rows)
- Set `clinical_decision_applied_at` after successful commit
- Only advance watermark on consecutive successes

### Step 3: Verify

1. Check that new messages are being processed:
   ```sql
   SELECT COUNT(*) 
   FROM service_ops.send_serviceops 
   WHERE clinical_ops_decision_json IS NOT NULL 
     AND clinical_decision_applied_at IS NULL;
   ```

2. Check that decisions are being applied:
   ```sql
   SELECT COUNT(*) 
   FROM service_ops.send_serviceops 
   WHERE clinical_ops_decision_json IS NOT NULL 
     AND clinical_decision_applied_at IS NOT NULL;
   ```

3. Monitor logs for "Applying clinical decision" messages

## Testing

### Unit Tests

Run the comprehensive unit tests:

```bash
pytest tests/test_clinical_ops_inbox_processor.py -v
```

**New tests added**:
- `test_phase2_row_always_applies_decision`: Verifies Phase 2 rows also apply decision
- `test_mark_decision_applied_sets_timestamp`: Verifies `clinical_decision_applied_at` is set
- `test_watermark_stops_at_first_failure`: Verifies watermark only advances to last consecutive success
- `test_poll_filters_by_applied_at_column`: Verifies poll query filters by `clinical_decision_applied_at IS NULL`
- `test_poll_uses_skip_locked`: Verifies poll query uses `FOR UPDATE SKIP LOCKED`

### Integration Testing

1. **Test Phase 2 row gets decision applied**:
   - Create a row with `json_sent_to_integration = true` and `clinical_decision_applied_at = NULL`
   - Run processor
   - Verify decision is applied and `clinical_decision_applied_at` is set

2. **Test watermark stops at failure**:
   - Create 3 messages in order
   - Make middle message fail (e.g. packet not found)
   - Run processor
   - Verify watermark only advances to first message (not third)

3. **Test retry on failure**:
   - Create a message that will fail (e.g. packet not found)
   - Run processor (should fail)
   - Fix the issue (e.g. create packet)
   - Run processor again (should succeed)

## Benefits

1. **100% Reliability**: Decisions are always applied, even if downstream steps fail
2. **Automatic Retry**: Failed messages are automatically retried (not skipped by watermark)
3. **No Duplicate Processing**: Row-level locking prevents duplicate processing
4. **Auditable**: `clinical_decision_applied_at` provides clear audit trail
5. **Idempotent**: Applying the same decision again is a no-op
6. **Simple**: One code path for "apply decision from JSON"

## Rollback Plan

If issues arise, rollback steps:

1. **Revert code**: Deploy previous version of `clinical_ops_inbox_processor.py`
2. **Keep column**: The `clinical_decision_applied_at` column can remain (it's nullable and doesn't break old code)
3. **Reset watermark**: If needed, reset watermark to reprocess messages:
   ```sql
   UPDATE service_ops.clinical_ops_poll_watermark
   SET last_created_at = '2026-01-01 00:00:00+00'::timestamptz,
       last_message_id = 0
   WHERE id = 1;
   ```

## Monitoring

Monitor these metrics:

1. **Unapplied decisions count**:
   ```sql
   SELECT COUNT(*) 
   FROM service_ops.send_serviceops 
   WHERE clinical_ops_decision_json IS NOT NULL 
     AND clinical_decision_applied_at IS NULL;
   ```

2. **Processing rate**: Monitor logs for "Applying clinical decision" messages

3. **Failure rate**: Monitor logs for "Error processing ClinicalOps message" messages

4. **Watermark position**: Check watermark to see how far processing has advanced

## Future Enhancements

Optional improvements:

1. **Failure tracking**: Add `last_decision_apply_error` and `last_decision_apply_attempt_at` columns
2. **Retry cap**: After N attempts, mark as "skip" and alert
3. **Metrics dashboard**: Show unapplied decisions count, processing rate, failure rate
