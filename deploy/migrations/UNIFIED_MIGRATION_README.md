# Unified Migration 017-022 - Complete Guide

## Overview

This document provides a complete guide for the unified migration script that consolidates migrations 017-022 into a single, idempotent script that handles the current production database state.

## Files Created

1. **`UNIFIED_MIGRATION_017_022.sql`** - Main migration script (run this)
2. **`VERIFY_UNIFIED_MIGRATION.sql`** - Verification queries (run after migration)
3. **`ROLLBACK_UNIFIED_MIGRATION.sql`** - Rollback script (use only if needed)
4. **`MIGRATION_GAP_ANALYSIS.md`** - Detailed gap analysis
5. **`UNIFIED_MIGRATION_README.md`** - This file

## Current Production State

Based on your analysis:
- **Migration 017**: NOT APPLIED
- **Migration 018**: PARTIALLY APPLIED (`send_integration` table exists with 9/15 columns)
- **Migration 019**: CANNOT RUN (table missing - but migration 015 should have created it)
- **Migrations 020-022**: NOT APPLIED

## What the Unified Script Does

The unified script consolidates all migrations 017-022 and:

1. ✅ **Handles existing `send_integration` table** - Adds missing columns instead of recreating
2. ✅ **Creates `clinical_ops_poll_watermark` if missing** - Ensures migration 019 can run
3. ✅ **Safely converts timezone columns** - Only converts if needed, checks data type first
4. ✅ **Is fully idempotent** - Safe to run multiple times
5. ✅ **Preserves existing data** - Uses UPDATE before NOT NULL, safe defaults

## Migration Contents

### Migration 017: New Workflow Schema
- Adds `validation_status` to `packet` (with CHECK constraint)
- Updates `detailed_status` to NOT NULL (with CHECK constraint)
- Adds `operational_decision` and `clinical_decision` to `packet_decision`
- Creates `packet_validation` table
- Adds audit trail fields (`is_active`, `supersedes`, `superseded_by`)

### Migration 018: Create send_integration Table
- Creates table if missing
- Adds all missing columns to existing table
- Creates all indexes
- Adds all foreign keys

### Migration 019: Update ClinicalOps Watermark
- Creates `clinical_ops_poll_watermark` table if missing
- Adds `last_created_at` column (TIMESTAMPTZ)

### Migration 020: Fix Timezone Columns
- Converts `send_serviceops.created_at` to TIMESTAMPTZ (if needed)
- Converts `integration_poll_watermark.last_created_at` to TIMESTAMPTZ (if needed)

### Migration 021: Complete send_integration Structure
- Ensures all columns from migration 018 are present
- Creates correlation_id index

### Migration 022: Add json_sent_to_integration Flag
- Adds `json_sent_to_integration` column (DEFAULT NULL)
- Creates index for faster lookups
- Updates any incorrectly set FALSE values to NULL

## Execution Instructions

### Step 1: Pre-Migration Checklist

- [ ] Backup production database
- [ ] Review `MIGRATION_GAP_ANALYSIS.md` for detailed analysis
- [ ] Verify you have database connection credentials
- [ ] Ensure you have sufficient privileges (ALTER TABLE, CREATE TABLE, etc.)
- [ ] Check maintenance window availability

### Step 2: Run Unified Migration

```bash
# Connect to production database
psql -h <host> -U <user> -d <database>

# Run the unified migration
\i UNIFIED_MIGRATION_017_022.sql
```

Or using environment variables:
```bash
export PGHOST=prd-wiser-psql.postgres.database.usgovcloudapi.net
export PGUSER=wiserpgadmin
export PGPORT=5432
export PGDATABASE=postgres
export PGPASSWORD=<password>

psql -f UNIFIED_MIGRATION_017_022.sql
```

### Step 3: Verify Migration

```bash
# Run verification queries
psql -f VERIFY_UNIFIED_MIGRATION.sql
```

Review all results - all checks should show "PASS".

### Step 4: Post-Migration Tasks

- [ ] Verify application can connect to database
- [ ] Test new workflow features
- [ ] Monitor application logs for errors
- [ ] Check that existing data is intact

## Key Features

### Idempotency

The script is designed to be **safe to run multiple times**. It uses:
- `IF NOT EXISTS` for tables and indexes
- `ADD COLUMN IF NOT EXISTS` for columns
- `DROP CONSTRAINT IF EXISTS` before adding constraints
- DO blocks to check existence before operations

### Data Safety

- **UPDATE before NOT NULL**: Sets defaults for existing records before making columns NOT NULL
- **Safe timezone conversion**: Only converts if column is TIMESTAMP (not TIMESTAMPTZ)
- **Preserves existing data**: No data loss, only additions

### Error Handling

- All operations are wrapped in DO blocks with existence checks
- Foreign keys are only added if referenced tables exist
- Timezone conversions only happen if needed

## Troubleshooting

### Issue: Foreign key constraint fails

**Cause**: Referenced table (`message_status` or `workflow_instance`) doesn't exist

**Solution**: The script will skip adding the foreign key if the referenced table doesn't exist. This is safe - the foreign key can be added later when the table is created.

### Issue: Timezone conversion fails

**Cause**: Column might not exist or might already be TIMESTAMPTZ

**Solution**: The script checks for this and only converts if needed. If it still fails, check the column exists and has data.

### Issue: Constraint violation on existing data

**Cause**: Existing data doesn't match new CHECK constraint values

**Solution**: The script sets defaults for existing records. If you still get violations, you may need to update data manually before running the migration.

### Issue: Table already exists error

**Cause**: Table was created manually with different structure

**Solution**: The script uses `CREATE TABLE IF NOT EXISTS`, so this shouldn't happen. If it does, check the table structure matches expected schema.

## Rollback Instructions

⚠️ **WARNING**: Rollback will remove all changes and may result in data loss.

If you need to rollback:

1. **Backup database first**
2. Review `ROLLBACK_UNIFIED_MIGRATION.sql`
3. Uncomment sections you want to rollback
4. Run the rollback script

**Note**: The rollback script is conservative - it doesn't drop tables by default to preserve data. Uncomment sections as needed.

## Verification Checklist

After running the migration, verify:

- [ ] `packet.validation_status` exists and is NOT NULL
- [ ] `packet.detailed_status` is NOT NULL
- [ ] `packet_decision.operational_decision` exists and is NOT NULL
- [ ] `packet_decision.clinical_decision` exists and is NOT NULL
- [ ] `packet_decision.is_active`, `supersedes`, `superseded_by` exist
- [ ] `packet_validation` table exists
- [ ] `send_integration` table has all 15 columns
- [ ] `send_integration` has all indexes
- [ ] `send_integration` has all foreign keys (if referenced tables exist)
- [ ] `send_serviceops.json_sent_to_integration` exists (DEFAULT NULL)
- [ ] `send_serviceops.created_at` is TIMESTAMPTZ
- [ ] `clinical_ops_poll_watermark.last_created_at` exists (TIMESTAMPTZ)
- [ ] `integration_poll_watermark.last_created_at` is TIMESTAMPTZ

## Support

If you encounter issues:

1. Check `MIGRATION_GAP_ANALYSIS.md` for detailed analysis
2. Review error messages carefully
3. Check that all prerequisites are met
4. Verify database connection and permissions
5. Check application logs for related errors

## Success Criteria

The migration is successful if:

- ✅ Script completes without errors
- ✅ All verification queries show "PASS"
- ✅ Application can connect and function normally
- ✅ Existing data is intact
- ✅ New features work as expected

## Next Steps

After successful migration:

1. Monitor application performance
2. Test new workflow features
3. Update application code if needed
4. Document any issues encountered
5. Update migration tracking/logging

---

**Created**: 2026-01-XX  
**Last Updated**: 2026-01-XX  
**Version**: 1.0

