-- Cleanup script for channel testing
-- Clears all related tables, keeping only the 3 test records in send_serviceops
-- Run this AFTER migration 010

BEGIN;

-- ============================================================================
-- 1. Clear service_ops tables (in dependency order)
-- ============================================================================

-- Clear decisions and validations first (they reference documents)
DELETE FROM service_ops.packet_decision;
DELETE FROM service_ops.validation_run;

-- Clear documents (they reference packets)
DELETE FROM service_ops.packet_document;

-- Clear packets
DELETE FROM service_ops.packet;

-- Clear inbox (processing queue)
DELETE FROM service_ops.integration_inbox;

-- Reset watermark to start fresh
UPDATE service_ops.integration_poll_watermark
SET 
    last_created_at = '1970-01-01 00:00:00',
    last_message_id = 0,
    updated_at = NOW()
WHERE id = 1;

-- ============================================================================
-- 2. Clean integration.send_serviceops - Keep only 3 test records
-- ============================================================================

-- Delete all except the 3 test records (270, 271, 272)
DELETE FROM integration.send_serviceops
WHERE message_id NOT IN (270, 271, 272);

-- Verify only 3 records remain
DO $$
DECLARE
    record_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO record_count
    FROM integration.send_serviceops
    WHERE is_deleted = false;
    
    IF record_count != 3 THEN
        RAISE EXCEPTION 'Expected 3 records in send_serviceops, found %', record_count;
    END IF;
    
    RAISE NOTICE '✓ Verified: 3 records in send_serviceops';
END $$;

COMMIT;

-- ============================================================================
-- Verification queries (run after cleanup)
-- ============================================================================
-- SELECT COUNT(*) FROM service_ops.packet; -- Should be 0
-- SELECT COUNT(*) FROM service_ops.packet_document; -- Should be 0
-- SELECT COUNT(*) FROM service_ops.integration_inbox; -- Should be 0
-- SELECT COUNT(*) FROM integration.send_serviceops WHERE is_deleted = false; -- Should be 3
-- SELECT message_id, channel_type_id, decision_tracking_id FROM integration.send_serviceops WHERE is_deleted = false ORDER BY message_id;






