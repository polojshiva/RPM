# Migration Gap Analysis: Code Dependencies vs Migrations 017-022

## Executive Summary

This document analyzes the gap between what the code expects and what migrations 017-022 provide. All critical gaps have been identified and will be addressed in the unified migration script.

## Code Dependencies Analysis

### Database Objects Expected by Code

#### 1. `service_ops.packet` table
**Expected Columns:**
- `validation_status` TEXT NOT NULL (with CHECK constraint)
- `detailed_status` TEXT NOT NULL (with CHECK constraint)

**Status**: ✅ Covered by Migration 017

#### 2. `service_ops.packet_decision` table
**Expected Columns:**
- `operational_decision` TEXT NOT NULL (with CHECK constraint)
- `clinical_decision` TEXT NOT NULL (with CHECK constraint)
- `is_active` BOOLEAN NOT NULL
- `supersedes` BIGINT (FK to packet_decision)
- `superseded_by` BIGINT (FK to packet_decision)

**Status**: ✅ Covered by Migration 017

#### 3. `service_ops.packet_validation` table
**Expected Structure:**
- Full table with all columns, indexes, and foreign keys

**Status**: ✅ Covered by Migration 017

#### 4. `service_ops.send_integration` table
**Expected Columns (from models):**
- `message_id` BIGINT PRIMARY KEY
- `decision_tracking_id` UUID NOT NULL
- `workflow_instance_id` BIGINT (nullable, FK to workflow_instance)
- `payload` JSONB NOT NULL
- `message_status_id` INTEGER (nullable, FK to message_status)
- `correlation_id` UUID (nullable)
- `attempt_count` INTEGER (default 1)
- `resend_of_message_id` BIGINT (nullable, FK to send_integration)
- `payload_hash` TEXT (nullable)
- `payload_version` INTEGER (default 1)
- `created_at` TIMESTAMPTZ
- `updated_at` TIMESTAMPTZ (nullable)
- `audit_user` VARCHAR(100) (nullable)
- `audit_timestamp` TIMESTAMPTZ
- `is_deleted` BOOLEAN (default false)

**Expected Indexes:**
- `idx_send_integration_decision_tracking`
- `idx_send_integration_message_status`
- `idx_send_integration_correlation_id`
- `idx_send_integration_resend`
- `idx_send_integration_attempt_count`
- `idx_send_integration_decision_attempt`
- `idx_send_integration_created_at`
- `idx_send_integration_payload_gin`
- `idx_send_integration_message_type`

**Expected Foreign Keys:**
- `fk_send_integration_message_status` → `service_ops.message_status(message_status_id)`
- `fk_send_integration_workflow_instance` → `service_ops.workflow_instance(workflow_instance_id)`
- `fk_send_integration_resend` → `service_ops.send_integration(message_id)`

**Status**: ⚠️ **PARTIALLY COVERED**
- Migration 018 creates table but table already exists in production with 9/15 columns
- Migration 021 adds missing columns
- **Gap**: Need to handle existing table gracefully, add missing columns, ensure all indexes and FKs exist

#### 5. `service_ops.send_serviceops` table
**Expected Columns:**
- `json_sent_to_integration` BOOLEAN (nullable, DEFAULT NULL)
- `created_at` TIMESTAMPTZ (not TIMESTAMP)

**Expected Indexes:**
- `idx_send_serviceops_json_sent` (partial index on decision_tracking_id, json_sent_to_integration WHERE json_sent_to_integration IS NOT NULL)

**Status**: ⚠️ **PARTIALLY COVERED**
- Migration 022 adds `json_sent_to_integration` ✅
- Migration 020 converts `created_at` to TIMESTAMPTZ ⚠️ (needs safety check)

#### 6. `service_ops.clinical_ops_poll_watermark` table
**Expected Columns:**
- `last_created_at` TIMESTAMPTZ NOT NULL

**Status**: ⚠️ **PARTIALLY COVERED**
- Migration 015 creates table (should exist)
- Migration 019 adds `last_created_at` column
- **Gap**: If table doesn't exist, migration 019 will fail

#### 7. `service_ops.integration_poll_watermark` table
**Expected Columns:**
- `last_created_at` TIMESTAMPTZ (not TIMESTAMP)

**Status**: ⚠️ **PARTIALLY COVERED**
- Migration 020 converts to TIMESTAMPTZ ⚠️ (needs safety check)

## Gap Analysis

### Critical Gaps

#### Gap 1: Migration 018 - Table Already Exists
**Issue**: `send_integration` table exists in production with partial structure (9/15 columns)

**Missing Columns:**
- `correlation_id` UUID
- `attempt_count` INTEGER
- `resend_of_message_id` BIGINT
- `payload_hash` TEXT
- `payload_version` INTEGER
- `updated_at` TIMESTAMPTZ

**Missing Indexes:**
- All indexes from migration 018 (if table was created manually)

**Missing Foreign Keys:**
- All foreign keys from migration 018 (if table was created manually)

**Solution**: Unified script will:
1. Check if table exists
2. Add missing columns using `IF NOT EXISTS`
3. Create missing indexes
4. Add missing foreign keys (with `IF NOT EXISTS`)

#### Gap 2: Migration 019 - Table Dependency
**Issue**: Migration 019 assumes `clinical_ops_poll_watermark` exists (from migration 015)

**Solution**: Unified script will:
1. Check if table exists
2. Create it if missing (using migration 015 structure)
3. Then add `last_created_at` column

#### Gap 3: Migration 020 - Unsafe Timezone Conversion
**Issue**: Migration 020 tries to ALTER column type without checking:
- If column exists
- If column is already TIMESTAMPTZ
- If table exists

**Solution**: Unified script will:
1. Check if table and column exist
2. Check current data type
3. Only convert if needed (TIMESTAMP → TIMESTAMPTZ)
4. Handle empty tables safely

#### Gap 4: Foreign Key Constraints
**Issue**: Migration 018 creates foreign keys, but if table exists, FKs might be missing

**Solution**: Unified script will:
1. Check if foreign keys exist
2. Add them if missing (with `IF NOT EXISTS` equivalent using DO blocks)

### Minor Gaps

#### Gap 5: Index Creation Order
**Issue**: Some indexes might already exist from partial migration 018

**Solution**: All indexes use `CREATE INDEX IF NOT EXISTS` ✅

#### Gap 6: Constraint Handling
**Issue**: CHECK constraints might need to be dropped and recreated if values changed

**Solution**: Migrations use `DROP CONSTRAINT IF EXISTS` before adding ✅

## Migration Order Dependencies

1. **Migration 015** (prerequisite for 019): Creates `clinical_ops_poll_watermark`
2. **Migration 017**: No dependencies
3. **Migration 018**: Creates `send_integration` (but exists partially)
4. **Migration 019**: Depends on 015 (table must exist)
5. **Migration 020**: Depends on tables existing
6. **Migration 021**: Depends on 018 (table must exist)
7. **Migration 022**: No dependencies

## Unified Script Strategy

The unified script will:

1. **Handle existing state gracefully**:
   - Check for existing tables/columns before creating/adding
   - Use `IF NOT EXISTS` everywhere
   - Add missing columns to existing tables

2. **Respect dependencies**:
   - Create `clinical_ops_poll_watermark` if missing (before migration 019)
   - Ensure `send_integration` exists before adding columns
   - Handle timezone conversions safely

3. **Be idempotent**:
   - Safe to run multiple times
   - Won't fail if partially applied
   - Won't duplicate objects

4. **Preserve data**:
   - UPDATE before NOT NULL
   - Safe timezone conversions
   - Default values for existing records

## Verification Checklist

After running unified script, verify:

- [ ] `packet.validation_status` exists with CHECK constraint
- [ ] `packet.detailed_status` is NOT NULL with CHECK constraint
- [ ] `packet_decision.operational_decision` exists with CHECK constraint
- [ ] `packet_decision.clinical_decision` exists with CHECK constraint
- [ ] `packet_decision.is_active`, `supersedes`, `superseded_by` exist
- [ ] `packet_validation` table exists with all columns and indexes
- [ ] `send_integration` table has all 15 columns
- [ ] `send_integration` has all indexes
- [ ] `send_integration` has all foreign keys
- [ ] `send_serviceops.json_sent_to_integration` exists (DEFAULT NULL)
- [ ] `send_serviceops.created_at` is TIMESTAMPTZ
- [ ] `clinical_ops_poll_watermark.last_created_at` exists (TIMESTAMPTZ)
- [ ] `integration_poll_watermark.last_created_at` is TIMESTAMPTZ

## Conclusion

All gaps have been identified and will be addressed in the unified migration script. The script will:
- ✅ Handle existing `send_integration` table gracefully
- ✅ Create missing `clinical_ops_poll_watermark` if needed
- ✅ Safely convert timezone columns
- ✅ Add all missing columns, indexes, and foreign keys
- ✅ Be fully idempotent and safe for production

