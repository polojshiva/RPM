# Migration Scripts - DBA Instructions

## Quick Summary

- **Total SQL Files**: 26
- **Actual Migrations**: 19 (numbered 001-020)
- **New Migrations**: 2 (019, 020) - **MUST RUN**
- **Test/Reference Files**: 7 (DO NOT RUN)

## Migration Files (Run in Order)

Run these migrations in numerical order:

1. `001_create_integration_inbox.sql`
2. `002_add_page_tracking_to_packet_document.sql`
3. `003_add_document_unique_identifier.sql`
4. `004_enforce_single_consolidated_document.sql`
5. `005_add_submission_type_to_packet.sql`
6. `006_add_manual_review_fields_to_packet_document.sql`
7. `007_add_suggested_extracted_fields.sql`
8. `008_create_validations_and_decisions.sql`
9. `009_add_decision_tracking_id_to_packet.sql`
10. `010_add_channel_type_id_to_integration_inbox.sql`
11. `011_extend_integration_inbox_for_utn_workflow.sql`
12. `012_extend_packet_decision_for_utn_workflow.sql`
13. `013_extend_integration_receive_serviceops_for_utn_workflow.sql`
14. `015_create_clinical_ops_watermark.sql`
15. `016_add_letter_status_failed.sql`
16. `017_new_workflow_schema.sql` ⭐ **CRITICAL**
17. `018_create_send_integration_table.sql` ⭐ **CRITICAL**
18. `019_update_clinical_ops_watermark_strategy.sql` ⭐ **NEW - MUST RUN**
19. `020_fix_timezone_columns.sql` ⭐ **NEW - MUST RUN**

## Files to SKIP (Test/Reference Only)

- `002_integration_inbox_queries.sql`
- `003_test_integration_inbox.sql`
- `003_verify_migration_002.sql`
- `004_manual_insert_test.sql`
- `009_validate_no_duplicates.sql`
- `014_verify_utn_workflow_migrations.sql`
- `STAGE_1_UTN_WORKFLOW_MIGRATIONS.sql`
- `DBA_INSTRUCTIONS_STAGE_1.md`

## Pre-Migration Checklist

1. ✅ Backup database
2. ✅ Verify database timezone is UTC: `SHOW timezone;` (should be 'UTC')
3. ✅ Check which migrations have already been run (see verification queries below)
4. ✅ Test in test environment first

## Verification Queries

### Check if Migration 017 was run:
```sql
SELECT column_name FROM information_schema.columns 
WHERE table_schema = 'service_ops' 
AND table_name = 'packet' 
AND column_name = 'validation_status';
-- If returns a row, migration 017 was run
```

### Check if Migration 018 was run:
```sql
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'service_ops' 
AND table_name = 'send_integration';
-- If returns a row, migration 018 was run
```

### Check if Migration 019 was run:
```sql
SELECT column_name FROM information_schema.columns 
WHERE table_schema = 'service_ops' 
AND table_name = 'clinical_ops_poll_watermark' 
AND column_name = 'last_created_at';
-- If returns a row, migration 019 was run
```

### Check if Migration 020 was run:
```sql
SELECT data_type FROM information_schema.columns 
WHERE table_schema = 'service_ops' 
AND table_name = 'send_serviceops' 
AND column_name = 'created_at';
-- If returns 'timestamp with time zone', migration 020 was run
```

## Post-Migration Verification

After running migrations, verify all timestamp columns are TIMESTAMPTZ:

```sql
SELECT 
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema IN ('service_ops', 'integration')
AND data_type LIKE '%timestamp%'
AND column_name IN ('created_at', 'last_created_at', 'updated_at')
ORDER BY table_schema, table_name, column_name;
-- All should return: timestamp with time zone
```

## Execution Order

**CRITICAL**: Run migrations in numerical order (001, 002, 003, ..., 020).

If some migrations have already been run, skip them and run only the missing ones.

## Minimum Required Migrations

If you're unsure what's been run, at minimum run:
- `017_new_workflow_schema.sql`
- `018_create_send_integration_table.sql`
- `019_update_clinical_ops_watermark_strategy.sql`
- `020_fix_timezone_columns.sql`

## Troubleshooting

1. **Error: relation already exists**
   - Migration was already run, skip it

2. **Error: column already exists**
   - Migration was already run, skip it

3. **Error: timezone conversion**
   - Ensure database timezone is UTC: `SET timezone = 'UTC';`

4. **Error: constraint violation**
   - Check if data exists that violates new constraints
   - May need to clean/update data before running migration

## Contact

For questions or issues, refer to:
- `MIGRATION_SCRIPTS_SUMMARY.md` - Detailed migration documentation
- `DBA_MIGRATION_CHECKLIST.md` - Complete checklist

