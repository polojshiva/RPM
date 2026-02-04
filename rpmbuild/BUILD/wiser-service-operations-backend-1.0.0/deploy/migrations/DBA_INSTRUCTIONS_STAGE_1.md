# DBA Instructions: Stage 1 UTN Workflow Migrations

**Date:** 2026-01-XX  
**Script:** `STAGE_1_UTN_WORKFLOW_MIGRATIONS.sql`

---

## Overview

This migration extends the database schema to support UTN (Unique Tracking Number) workflow for ServiceOps. It includes:

1. **Integration Inbox Updates** - Fix idempotency for UTN events, add routing support
2. **Packet Decision Extensions** - Add 20 workflow tracking fields for ESMD/UTN/letter state
3. **Integration Outbox Extensions** - Add resend tracking and payload versioning

---

## Pre-Migration Checklist

- [ ] Backup production database
- [ ] Review migration script (`STAGE_1_UTN_WORKFLOW_MIGRATIONS.sql`)
- [ ] Verify database connection
- [ ] Check current table structures match expected state
- [ ] Plan rollback procedure (see Rollback section below)

---

## How to Run

### Option 1: Run with Transaction (Recommended)

```bash
psql -U <db_user> -d wiser_ops -f STAGE_1_UTN_WORKFLOW_MIGRATIONS.sql
```

**Note:** The script uses `BEGIN;` at the start. You must manually `COMMIT;` or `ROLLBACK;` at the end after reviewing verification results.

### Option 2: Run Interactively

```bash
psql -U <db_user> -d wiser_ops
```

Then copy/paste the migration script content. Review verification results, then:
- If all checks pass: `COMMIT;`
- If any checks fail: `ROLLBACK;`

---

## What This Migration Does

### 1. service_ops.integration_inbox

**Adds:**
- `message_type_id` column (INTEGER) - For routing messages by type
- Unique constraint on `message_id` - Idempotency for all message types
- Index on `message_type_id` - For efficient routing queries

**Removes:**
- Old unique constraint `(decision_tracking_id, message_type)` - Blocks UTN retries

**Updates:**
- Sets `message_type_id = 1` for existing rows (backward compatibility)

### 2. service_ops.packet_decision

**Adds 20 columns:**
- Decision context: `decision_subtype`, `decision_outcome`, `part_type`
- ESMD tracking: `esmd_request_status`, `esmd_request_payload`, `esmd_request_payload_history`, `esmd_attempt_count`, `esmd_last_sent_at`, `esmd_last_error`
- UTN tracking: `utn`, `utn_status`, `utn_received_at`, `utn_fail_payload`, `utn_action_required`, `requires_utn_fix`
- Letter tracking: `letter_owner`, `letter_status`, `letter_package`, `letter_medical_docs`, `letter_generated_at`, `letter_sent_to_integration_at`

**Adds 5 indexes:**
- For UTN status, requires_utn_fix, ESMD status, letter status, decision outcome queries

### 3. integration.integration_receive_serviceops

**Adds 5 columns:**
- `correlation_id` (UUID) - For tracking resends
- `attempt_count` (INTEGER) - Number of attempts
- `resend_of_response_id` (BIGINT) - Link to previous response
- `payload_hash` (TEXT) - SHA-256 hash for audit
- `payload_version` (INTEGER) - Payload version number

**Adds:**
- Foreign key constraint `fk_irs_resend_of_response_id` - For resend chain
- 4 indexes for efficient queries

---

## Verification

After running the migration, the script will automatically run verification queries showing:
- `PASS` - Change applied successfully
- `FAIL` - Change not applied (investigate before committing)

**Expected Results:**
- All 8 verification checks should show `PASS`

If any check shows `FAIL`:
1. **DO NOT COMMIT**
2. Investigate the failure
3. Check error logs
4. Rollback if needed

---

## Rollback Procedure

If you need to rollback, run these in reverse order:

### Rollback Migration 013

```sql
BEGIN;

ALTER TABLE integration.integration_receive_serviceops
DROP CONSTRAINT IF EXISTS fk_irs_resend_of_response_id;

DROP INDEX IF EXISTS integration.idx_irs_correlation_id;
DROP INDEX IF EXISTS integration.idx_irs_resend_of_response_id;
DROP INDEX IF EXISTS integration.idx_irs_attempt_count;
DROP INDEX IF EXISTS integration.idx_irs_decision_attempt;

ALTER TABLE integration.integration_receive_serviceops
DROP COLUMN IF EXISTS correlation_id,
DROP COLUMN IF EXISTS attempt_count,
DROP COLUMN IF EXISTS resend_of_response_id,
DROP COLUMN IF EXISTS payload_hash,
DROP COLUMN IF EXISTS payload_version;

COMMIT;
```

### Rollback Migration 012

```sql
BEGIN;

DROP INDEX IF EXISTS service_ops.idx_packet_decision_utn_status;
DROP INDEX IF EXISTS service_ops.idx_packet_decision_requires_utn_fix;
DROP INDEX IF EXISTS service_ops.idx_packet_decision_esmd_request_status;
DROP INDEX IF EXISTS service_ops.idx_packet_decision_letter_status;
DROP INDEX IF EXISTS service_ops.idx_packet_decision_decision_outcome;

ALTER TABLE service_ops.packet_decision
DROP COLUMN IF EXISTS decision_subtype,
DROP COLUMN IF EXISTS decision_outcome,
DROP COLUMN IF EXISTS part_type,
DROP COLUMN IF EXISTS esmd_request_status,
DROP COLUMN IF EXISTS esmd_request_payload,
DROP COLUMN IF EXISTS esmd_request_payload_history,
DROP COLUMN IF EXISTS esmd_attempt_count,
DROP COLUMN IF EXISTS esmd_last_sent_at,
DROP COLUMN IF EXISTS esmd_last_error,
DROP COLUMN IF EXISTS utn,
DROP COLUMN IF EXISTS utn_status,
DROP COLUMN IF EXISTS utn_received_at,
DROP COLUMN IF EXISTS utn_fail_payload,
DROP COLUMN IF EXISTS utn_action_required,
DROP COLUMN IF EXISTS requires_utn_fix,
DROP COLUMN IF EXISTS letter_owner,
DROP COLUMN IF EXISTS letter_status,
DROP COLUMN IF EXISTS letter_package,
DROP COLUMN IF EXISTS letter_medical_docs,
DROP COLUMN IF EXISTS letter_generated_at,
DROP COLUMN IF EXISTS letter_sent_to_integration_at;

COMMIT;
```

### Rollback Migration 011

```sql
BEGIN;

DROP INDEX IF EXISTS service_ops.idx_integration_inbox_message_type_id;
DROP INDEX IF EXISTS service_ops.uq_integration_inbox_message_id;

ALTER TABLE service_ops.integration_inbox
DROP COLUMN IF EXISTS message_type_id;

-- Restore old constraint (if needed)
ALTER TABLE service_ops.integration_inbox
ADD CONSTRAINT uq_integration_inbox_decision_message 
UNIQUE (decision_tracking_id, message_type);

COMMIT;
```

---

## Post-Migration Verification

After committing, verify with:

```sql
-- Check integration_inbox
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_schema = 'service_ops' 
AND table_name = 'integration_inbox' 
AND column_name = 'message_type_id';

-- Check packet_decision new columns count
SELECT COUNT(*) 
FROM information_schema.columns 
WHERE table_schema = 'service_ops' 
AND table_name = 'packet_decision' 
AND column_name IN (
    'decision_subtype', 'decision_outcome', 'part_type',
    'esmd_request_status', 'utn', 'utn_status', 'requires_utn_fix',
    'letter_owner', 'letter_status'
);

-- Check integration_receive_serviceops new columns
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_schema = 'integration' 
AND table_name = 'integration_receive_serviceops' 
AND column_name IN ('correlation_id', 'attempt_count', 'payload_version');
```

---

## Impact Assessment

**Tables Modified:**
- `service_ops.integration_inbox` - Adds 1 column, 1 constraint change, 2 indexes
- `service_ops.packet_decision` - Adds 20 columns, 5 indexes
- `integration.integration_receive_serviceops` - Adds 5 columns, 1 FK, 4 indexes

**Downtime Required:** None (all changes are additive or non-blocking)

**Performance Impact:** Minimal (adds indexes which may improve query performance)

**Data Migration:** None (all new columns are nullable with defaults)

---

## Support

If you encounter any issues:
1. Check PostgreSQL error logs
2. Verify table structures match expected state
3. Review verification query results
4. Contact development team if rollback is needed

---

**End of DBA Instructions**

