-- Clean Database for Fresh Testing
-- PRESERVES: service_ops.send_clinicalops (ClinicalOps outbox)
-- PRESERVES: integration.send_serviceops (test messages for reprocessing)
-- Cleans all other tables in service_ops schema

BEGIN;

-- ============================================================================
-- 1. Backup integration.send_serviceops (test messages)
-- ============================================================================

-- Create temporary table to store test messages
CREATE TEMP TABLE IF NOT EXISTS send_serviceops_backup AS
SELECT 
    message_id,
    decision_tracking_id,
    payload,
    channel_type_id,
    message_type_id,
    created_at,
    audit_user,
    audit_timestamp,
    is_deleted
FROM integration.send_serviceops
WHERE is_deleted = false;

-- ============================================================================
-- 2. Clean service_ops schema tables (in dependency order)
-- NOTE: We do NOT touch service_ops.send_clinicalops
-- ============================================================================

-- Clean tables that reference others first
TRUNCATE TABLE service_ops.packet_validation CASCADE;
TRUNCATE TABLE service_ops.packet_decision CASCADE;
TRUNCATE TABLE service_ops.packet_document CASCADE;
TRUNCATE TABLE service_ops.packet CASCADE;
TRUNCATE TABLE service_ops.integration_inbox CASCADE;

-- Clean validation_run if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables 
               WHERE table_schema = 'service_ops' 
               AND table_name = 'validation_run') THEN
        TRUNCATE TABLE service_ops.validation_run CASCADE;
    END IF;
END $$;

-- Reset watermark to start fresh
UPDATE service_ops.integration_poll_watermark
SET 
    last_created_at = '1970-01-01 00:00:00',
    last_message_id = 0,
    updated_at = NOW()
WHERE id = 1;

-- Reset clinical_ops_poll_watermark if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables 
               WHERE table_schema = 'service_ops' 
               AND table_name = 'clinical_ops_poll_watermark') THEN
        UPDATE service_ops.clinical_ops_poll_watermark
        SET 
            last_message_id = 0,
            updated_at = NOW()
        WHERE id = 1;
    END IF;
END $$;

-- ============================================================================
-- 3. Clean integration tables (except send_serviceops and send_clinicalops)
-- ============================================================================

TRUNCATE TABLE service_ops.send_integration CASCADE;

-- Only truncate clinical_ops_watermark if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables 
               WHERE table_schema = 'integration' 
               AND table_name = 'clinical_ops_watermark') THEN
        TRUNCATE TABLE integration.clinical_ops_watermark CASCADE;
    END IF;
END $$;

-- ============================================================================
-- 4. Clean integration.send_serviceops but preserve test messages
-- ============================================================================

TRUNCATE TABLE integration.send_serviceops CASCADE;

-- Restore test messages from backup
INSERT INTO integration.send_serviceops (
    message_id, 
    decision_tracking_id, 
    payload,
    channel_type_id,
    message_type_id,
    created_at,
    audit_user,
    audit_timestamp,
    is_deleted
)
SELECT 
    message_id,
    decision_tracking_id,
    payload,
    channel_type_id,
    message_type_id,
    created_at,
    audit_user,
    audit_timestamp,
    is_deleted
FROM send_serviceops_backup;

-- Drop temporary backup table
DROP TABLE IF EXISTS send_serviceops_backup;

-- ============================================================================
-- 5. Reset sequences (optional, but good for clean testing)
-- ============================================================================

-- Reset packet sequences
ALTER SEQUENCE IF EXISTS service_ops.packet_packet_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS service_ops.packet_document_packet_document_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS service_ops.packet_decision_packet_decision_id_seq RESTART WITH 1;
ALTER SEQUENCE IF EXISTS service_ops.packet_validation_packet_validation_id_seq RESTART WITH 1;

-- Reset integration sequences
ALTER SEQUENCE IF EXISTS service_ops.send_integration_message_id_seq RESTART WITH 1;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

SELECT 
    'service_ops.packet' AS table_name,
    COUNT(*) AS row_count
FROM service_ops.packet
UNION ALL
SELECT 
    'service_ops.packet_document',
    COUNT(*)
FROM service_ops.packet_document
UNION ALL
SELECT 
    'service_ops.packet_decision',
    COUNT(*)
FROM service_ops.packet_decision
UNION ALL
SELECT 
    'service_ops.packet_validation',
    COUNT(*)
FROM service_ops.packet_validation
UNION ALL
SELECT 
    'service_ops.send_clinicalops (PRESERVED)',
    COUNT(*)
FROM service_ops.send_clinicalops
UNION ALL
SELECT 
    'integration.send_serviceops (PRESERVED)',
    COUNT(*)
FROM integration.send_serviceops
WHERE is_deleted = false
UNION ALL
SELECT 
    'service_ops.send_integration',
    COUNT(*)
FROM service_ops.send_integration;

SELECT 
    '✓ Database cleaned successfully.' AS status,
    '✓ service_ops.send_clinicalops preserved' AS clinicalops_status,
    '✓ integration.send_serviceops test messages preserved' AS test_messages_status;

