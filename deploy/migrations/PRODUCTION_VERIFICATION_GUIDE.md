# Production Verification Guide

## Overview
This guide helps you verify that the migrations (017-022) are safe to run in production and won't affect older files/records processed in the old format.

## Critical Fix Applied

### ✅ Migration 022 - Fixed Default Value
**Issue**: Original migration set `DEFAULT FALSE`, but code expects `NULL` for old records.

**Fix Applied**: Changed to `DEFAULT NULL` and added safety UPDATE to fix any records that might have been incorrectly set to FALSE.

**Impact**: 
- Old records (non-generated payloads) will correctly be `NULL`
- New records from JSON Generator will have `TRUE` or `FALSE` explicitly set
- Code filters by `IS NOT NULL`, so old records won't be processed (correct behavior)

## Step-by-Step Verification Process

### Step 1: Connect to Production Database

Use the provided connection details:
```bash
export PGHOST=prd-wiser-psql.postgres.database.usgovcloudapi.net
export PGUSER=wiserpgadmin
export PGPORT=5432
export PGDATABASE=postgres
export PGPASSWORD=DauUhbv74u5QXm2
```

**Note**: You may need VPN or network access. If connection times out, contact your DBA.

### Step 2: Run Schema Check Queries

Run the queries from `PRODUCTION_SCHEMA_CHECK.sql` to verify:

1. **Current table structures** - Verify what columns exist
2. **Existing data counts** - Understand data volume
3. **Constraint violations** - Check for data that doesn't match new constraints
4. **Missing dependencies** - Verify required tables exist

### Step 3: Review Results

Key things to check:

#### ✅ Safe to Proceed If:
- `json_sent_to_integration` column does NOT exist in `send_serviceops`
- `send_integration` table does NOT exist (or exists with correct structure)
- `packet.validation_status` is NULL for existing records (will get default)
- `packet_decision.operational_decision` and `clinical_decision` are NULL (will get defaults)
- No constraint violations found

#### ⚠️ Review Required If:
- `json_sent_to_integration` already exists - Check its current default value
- `send_integration` table exists - Verify structure matches migration 018
- Existing `validation_status` values don't match new constraint - Need data migration
- Timezone columns are TIMESTAMP (not TIMESTAMPTZ) - Verify timezone of data

### Step 4: Migration Safety Analysis

#### Migration 017: New Workflow Schema
- ✅ **SAFE**: Sets defaults for existing NULL values
- ✅ **SAFE**: Updates existing records before making NOT NULL
- ⚠️ **CHECK**: Verify no existing `validation_status` values violate new constraint

#### Migration 018: Create send_integration Table
- ✅ **SAFE**: New table, doesn't affect existing records
- ✅ **SAFE**: Uses `CREATE TABLE IF NOT EXISTS`

#### Migration 019: Update ClinicalOps Watermark
- ✅ **SAFE**: Adds column with default
- ✅ **SAFE**: Updates existing records with epoch if NULL

#### Migration 020: Fix Timezone Columns
- ⚠️ **REVIEW**: Assumes existing TIMESTAMP values are UTC
- **Action**: Verify timezone of existing data before running

#### Migration 021: Add Missing send_integration Columns
- ✅ **SAFE**: Only adds columns if missing
- ✅ **SAFE**: Uses `IF NOT EXISTS` checks

#### Migration 022: Add json_sent_to_integration Flag (FIXED)
- ✅ **SAFE**: Now uses `DEFAULT NULL` (fixed)
- ✅ **SAFE**: Updates any incorrectly set FALSE values to NULL
- ✅ **SAFE**: Old records will be NULL (correct)

## Migration Execution Order

Run migrations in this order:
1. 017_new_workflow_schema.sql
2. 018_create_send_integration_table.sql
3. 019_update_clinical_ops_watermark_strategy.sql
4. 020_fix_timezone_columns.sql
5. 021_add_missing_send_integration_columns.sql
6. 022_add_json_sent_to_integration_flag.sql (FIXED)

## Post-Migration Verification

After running migrations, verify:

1. **Column exists with correct default**:
```sql
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'send_serviceops'
  AND column_name = 'json_sent_to_integration';
```

2. **Old records are NULL**:
```sql
SELECT 
    json_sent_to_integration,
    COUNT(*) as count
FROM service_ops.send_serviceops
GROUP BY json_sent_to_integration;
```
Expected: Most records should be NULL (old records)

3. **Index created**:
```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'service_ops'
  AND tablename = 'send_serviceops'
  AND indexname = 'idx_send_serviceops_json_sent';
```

## Rollback Plan

If issues occur:

1. **Migration 022 Rollback**:
```sql
-- Remove column (only if needed)
ALTER TABLE service_ops.send_serviceops
DROP COLUMN IF EXISTS json_sent_to_integration;

-- Remove index
DROP INDEX IF EXISTS service_ops.idx_send_serviceops_json_sent;
```

2. **Migration 017 Rollback** (if needed):
- More complex, see individual migration file for rollback steps

## Questions to Answer Before Production Deployment

1. ✅ Are all required tables (`message_status`, `workflow_instance`) present?
2. ✅ Do existing `validation_status` values match new constraint?
3. ✅ Are timezone columns TIMESTAMP or TIMESTAMPTZ? (for Migration 020)
4. ✅ How many records exist in `send_serviceops`? (to estimate migration time)
5. ✅ Is there a maintenance window for running migrations?

## Support

If you find issues during verification:
1. Document the issue in this file
2. Check `PRODUCTION_COMPATIBILITY_ANALYSIS.md` for detailed analysis
3. Review migration files for rollback procedures
4. Contact DBA if database-level issues are found

