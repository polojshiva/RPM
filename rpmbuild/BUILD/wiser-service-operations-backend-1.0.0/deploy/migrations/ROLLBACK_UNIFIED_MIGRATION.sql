-- ============================================================================
-- ROLLBACK SCRIPT: Unified Migration 017-022
-- WARNING: This script will remove all changes from migrations 017-022
-- Only run this if you need to completely rollback the unified migration
-- ============================================================================
-- 
-- IMPORTANT: 
-- - This script removes columns, tables, indexes, and constraints
-- - Data in removed columns will be LOST
-- - Review carefully before executing
-- - Consider backing up data first
-- ============================================================================

BEGIN;

-- ============================================================================
-- SECTION 1: Rollback Migration 022 - Remove json_sent_to_integration
-- ============================================================================

-- Remove index
DROP INDEX IF EXISTS service_ops.idx_send_serviceops_json_sent;

-- Remove column
ALTER TABLE service_ops.send_serviceops
DROP COLUMN IF EXISTS json_sent_to_integration;

-- ============================================================================
-- SECTION 2: Rollback Migration 021 - Remove send_integration columns
-- (Note: Migration 021 only adds columns, so we remove them here)
-- ============================================================================

-- Remove correlation_id index
DROP INDEX IF EXISTS service_ops.idx_send_integration_correlation_id;

-- Note: We don't remove columns here as they're part of migration 018
-- If you want to remove them, uncomment below:
/*
ALTER TABLE service_ops.send_integration
DROP COLUMN IF EXISTS correlation_id,
DROP COLUMN IF EXISTS attempt_count,
DROP COLUMN IF EXISTS resend_of_message_id,
DROP COLUMN IF EXISTS payload_hash,
DROP COLUMN IF EXISTS payload_version,
DROP COLUMN IF EXISTS updated_at;
*/

-- ============================================================================
-- SECTION 3: Rollback Migration 020 - Revert timezone conversions
-- WARNING: This converts TIMESTAMPTZ back to TIMESTAMP
-- ============================================================================

-- Revert send_serviceops.created_at to TIMESTAMP
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'send_serviceops'
          AND column_name = 'created_at'
          AND data_type = 'timestamp with time zone'
    ) THEN
        ALTER TABLE service_ops.send_serviceops
        ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE
        USING created_at::timestamp without time zone;
    END IF;
END $$;

-- Revert integration_poll_watermark.last_created_at to TIMESTAMP
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'integration_poll_watermark'
          AND column_name = 'last_created_at'
          AND data_type = 'timestamp with time zone'
    ) THEN
        ALTER TABLE service_ops.integration_poll_watermark
        ALTER COLUMN last_created_at TYPE TIMESTAMP WITHOUT TIME ZONE
        USING last_created_at::timestamp without time zone;
    END IF;
END $$;

-- ============================================================================
-- SECTION 4: Rollback Migration 019 - Remove last_created_at from watermark
-- ============================================================================

-- Remove last_created_at column (but keep table as it may be used elsewhere)
ALTER TABLE service_ops.clinical_ops_poll_watermark
DROP COLUMN IF EXISTS last_created_at;

-- Note: We don't drop the table as it may have been created by migration 015
-- If you want to drop it completely, uncomment below:
/*
DROP TABLE IF EXISTS service_ops.clinical_ops_poll_watermark;
*/

-- ============================================================================
-- SECTION 5: Rollback Migration 018 - Remove send_integration table
-- WARNING: This will DELETE ALL DATA in send_integration table
-- ============================================================================

-- Remove foreign keys first
ALTER TABLE service_ops.send_integration
DROP CONSTRAINT IF EXISTS fk_send_integration_resend,
DROP CONSTRAINT IF EXISTS fk_send_integration_workflow_instance,
DROP CONSTRAINT IF EXISTS fk_send_integration_message_status;

-- Remove indexes
DROP INDEX IF EXISTS service_ops.idx_send_integration_decision_tracking;
DROP INDEX IF EXISTS service_ops.idx_send_integration_message_status;
DROP INDEX IF EXISTS service_ops.idx_send_integration_correlation_id;
DROP INDEX IF EXISTS service_ops.idx_send_integration_resend;
DROP INDEX IF EXISTS service_ops.idx_send_integration_attempt_count;
DROP INDEX IF EXISTS service_ops.idx_send_integration_decision_attempt;
DROP INDEX IF EXISTS service_ops.idx_send_integration_created_at;
DROP INDEX IF EXISTS service_ops.idx_send_integration_payload_gin;
DROP INDEX IF EXISTS service_ops.idx_send_integration_message_type;

-- Drop table (WARNING: This deletes all data)
-- Uncomment to drop table:
/*
DROP TABLE IF EXISTS service_ops.send_integration;
*/

-- ============================================================================
-- SECTION 6: Rollback Migration 017 - Remove workflow schema changes
-- ============================================================================

-- 6.1 Remove packet_validation table
DROP TABLE IF EXISTS service_ops.packet_validation CASCADE;

-- 6.2 Remove packet_decision audit trail fields
ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS fk_packet_decision_superseded_by,
DROP CONSTRAINT IF EXISTS fk_packet_decision_supersedes;

DROP INDEX IF EXISTS service_ops.idx_packet_decision_active;

ALTER TABLE service_ops.packet_decision
DROP COLUMN IF EXISTS superseded_by,
DROP COLUMN IF EXISTS supersedes,
DROP COLUMN IF EXISTS is_active;

-- 6.3 Remove packet_decision decision columns
ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS check_clinical_decision,
DROP CONSTRAINT IF EXISTS check_operational_decision;

ALTER TABLE service_ops.packet_decision
DROP COLUMN IF EXISTS clinical_decision,
DROP COLUMN IF EXISTS operational_decision;

-- 6.4 Remove packet validation_status
ALTER TABLE service_ops.packet
DROP CONSTRAINT IF EXISTS check_validation_status;

ALTER TABLE service_ops.packet
DROP COLUMN IF EXISTS validation_status;

-- 6.5 Revert packet.detailed_status (remove constraint, make nullable)
ALTER TABLE service_ops.packet
DROP CONSTRAINT IF EXISTS check_detailed_status;

-- Make detailed_status nullable again
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet'
          AND column_name = 'detailed_status'
          AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE service_ops.packet
        ALTER COLUMN detailed_status DROP NOT NULL;
    END IF;
END $$;

-- Remove default (optional - you may want to keep it)
-- ALTER TABLE service_ops.packet
-- ALTER COLUMN detailed_status DROP DEFAULT;

-- 6.6 Revert letter_status constraint (restore original if needed)
-- Note: Original constraint may have been different
-- ALTER TABLE service_ops.packet_decision
-- DROP CONSTRAINT IF EXISTS check_letter_status;

COMMIT;

-- ============================================================================
-- VERIFICATION AFTER ROLLBACK
-- ============================================================================

-- Uncomment to verify rollback:
/*
-- Check that columns are removed
SELECT 
    'packet.validation_status removed' AS check_name,
    CASE 
        WHEN NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet'
              AND column_name = 'validation_status'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

SELECT 
    'packet_decision.operational_decision removed' AS check_name,
    CASE 
        WHEN NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_decision'
              AND column_name = 'operational_decision'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

SELECT 
    'send_serviceops.json_sent_to_integration removed' AS check_name,
    CASE 
        WHEN NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'send_serviceops'
              AND column_name = 'json_sent_to_integration'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

SELECT 'Rollback complete. Review all results above.' AS summary;
*/

