# Production Compatibility Analysis

## Overview
This document analyzes whether the new migrations (017-022) will affect older files/records that were processed in an older format.

## Key Migrations Analyzed

### Migration 017: New Workflow Schema
- **Changes**: Adds `validation_status`, `operational_decision`, `clinical_decision`, `packet_validation` table
- **Impact on Old Records**: 
  - ✅ **SAFE**: Sets defaults for existing NULL values
  - ✅ **SAFE**: Uses `UPDATE ... WHERE ... IS NULL` before making NOT NULL
  - ✅ **SAFE**: Old records get default values: `validation_status = 'Pending - Validation'`, `operational_decision = 'PENDING'`, `clinical_decision = 'PENDING'`

### Migration 018: Create send_integration Table
- **Changes**: Creates new `service_ops.send_integration` table
- **Impact on Old Records**: 
  - ✅ **SAFE**: New table, doesn't affect existing records
  - ✅ **SAFE**: Uses `CREATE TABLE IF NOT EXISTS`

### Migration 019: Update ClinicalOps Watermark Strategy
- **Changes**: Adds `last_created_at` to `clinical_ops_poll_watermark`
- **Impact on Old Records**: 
  - ✅ **SAFE**: Uses `ADD COLUMN IF NOT EXISTS` with default
  - ✅ **SAFE**: Updates existing records with epoch timestamp if NULL

### Migration 020: Fix Timezone Columns
- **Changes**: Converts TIMESTAMP to TIMESTAMPTZ
- **Impact on Old Records**: 
  - ⚠️ **POTENTIAL ISSUE**: Assumes existing values are UTC
  - ⚠️ **RISK**: If old records have local timezone, they'll be incorrectly converted
  - **Recommendation**: Verify timezone of existing records before migration

### Migration 021: Add Missing send_integration Columns
- **Changes**: Adds missing columns to `send_integration` if they don't exist
- **Impact on Old Records**: 
  - ✅ **SAFE**: Uses `IF NOT EXISTS` checks
  - ✅ **SAFE**: Only adds columns if missing

### Migration 022: Add json_sent_to_integration Flag
- **Changes**: Adds `json_sent_to_integration` to `service_ops.send_serviceops`
- **Impact on Old Records**: 
  - ⚠️ **ISSUE IDENTIFIED**: Migration sets `DEFAULT FALSE`, but code expects:
    - `NULL` = not a generated payload (old records)
    - `TRUE` = sent successfully
    - `FALSE` = failed to send
  - **Problem**: Existing records will get `FALSE` instead of `NULL`
  - **Impact**: Code filters by `IS NOT NULL`, so old records won't be processed (correct behavior), but semantically incorrect
  - **Recommendation**: Change default to `NULL` or update existing records to `NULL` after adding column

## Critical Issues Found

### Issue 1: Migration 022 - Default Value Mismatch
**Location**: `022_add_json_sent_to_integration_flag.sql` line 10

**Current Code**:
```sql
ADD COLUMN IF NOT EXISTS json_sent_to_integration BOOLEAN DEFAULT FALSE;
```

**Expected Behavior** (from code comments and processor):
- `NULL` = not a generated payload (old records)
- `TRUE` = sent successfully
- `FALSE` = failed to send

**Problem**: 
- Old records (non-generated payloads) will get `FALSE` instead of `NULL`
- While the code filters `IS NOT NULL` (so they won't be processed), the semantic meaning is wrong
- `FALSE` means "failed to send", not "not a generated payload"

**Fix Required**:
```sql
ADD COLUMN IF NOT EXISTS json_sent_to_integration BOOLEAN DEFAULT NULL;
```

Then update existing records:
```sql
-- Set existing records to NULL (they're not generated payloads)
UPDATE service_ops.send_serviceops
SET json_sent_to_integration = NULL
WHERE json_sent_to_integration = FALSE
  AND created_at < (SELECT MIN(created_at) FROM service_ops.send_integration WHERE created_at IS NOT NULL);
```

### Issue 2: Migration 020 - Timezone Conversion Assumption
**Location**: `020_fix_timezone_columns.sql`

**Problem**: 
- Assumes all existing TIMESTAMP values are UTC
- If old records have local timezone, they'll be incorrectly converted

**Recommendation**: 
- Query production to check if TIMESTAMP columns exist
- If they do, verify the timezone of existing data
- Consider adding a data migration to preserve original timestamps

## Safe Migrations (No Issues)

✅ **Migration 017**: Safe - sets defaults for existing records
✅ **Migration 018**: Safe - new table
✅ **Migration 019**: Safe - adds column with default
✅ **Migration 021**: Safe - only adds if missing

## Recommendations

1. **Fix Migration 022**: Change default to `NULL` and update existing records
2. **Verify Migration 020**: Check production timezone data before running
3. **Test in Staging**: Run all migrations in staging first with production data copy
4. **Backup**: Always backup production before running migrations

## Production Database Queries

See `PRODUCTION_SCHEMA_CHECK.sql` for queries to run against production to verify current state.

