-- Clean Database for Fresh Testing
-- Preserves only decision_tracking_id, payload, and message_id in integration.send_serviceops
-- Cleans all other tables in service_ops schema

BEGIN;

-- ============================================================================
-- 1. Backup the three key fields from integration.send_serviceops
-- ============================================================================

-- Create temporary table to store the three key fields
CREATE TEMP TABLE IF NOT EXISTS send_serviceops_backup AS
SELECT 
    message_id,
    decision_tracking_id,
    payload
FROM integration.send_serviceops
WHERE is_deleted = false;

-- ============================================================================
-- 2. Clean service_ops schema tables (in dependency order)
-- ============================================================================

-- Clean tables that reference others first
TRUNCATE TABLE service_ops.packet_validation CASCADE;
TRUNCATE TABLE service_ops.packet_decision CASCADE;
TRUNCATE TABLE service_ops.packet_document CASCADE;
TRUNCATE TABLE service_ops.packet CASCADE;
TRUNCATE TABLE service_ops.integration_inbox CASCADE;

-- Reset watermark to start fresh
UPDATE service_ops.integration_poll_watermark
SET 
    last_created_at = '1970-01-01 00:00:00',
    last_message_id = 0,
    updated_at = NOW()
WHERE id = 1;

-- Clean integration tables (except send_serviceops)
TRUNCATE TABLE integration.integration_receive_serviceops CASCADE;

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
-- 3. Clean integration.send_serviceops but preserve structure
-- ============================================================================

TRUNCATE TABLE integration.send_serviceops CASCADE;

-- ============================================================================
-- 4. Restore the three key fields to integration.send_serviceops
-- ============================================================================

-- Restore from backup (only the three key fields, other fields will use defaults)
INSERT INTO integration.send_serviceops (message_id, decision_tracking_id, payload)
SELECT 
    message_id,
    decision_tracking_id,
    payload
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
ALTER SEQUENCE IF EXISTS integration.integration_receive_serviceops_response_id_seq RESTART WITH 1;

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
    'integration.send_serviceops',
    COUNT(*)
FROM integration.send_serviceops
UNION ALL
SELECT 
    'integration.integration_receive_serviceops',
    COUNT(*)
FROM integration.integration_receive_serviceops;

SELECT 'Database cleaned successfully. send_serviceops preserved with message_id, decision_tracking_id, and payload.' AS status;

