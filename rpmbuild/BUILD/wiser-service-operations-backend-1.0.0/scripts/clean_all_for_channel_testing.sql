-- ============================================================================
-- Clean All ServiceOps Tables for Channel Testing
-- Keeps records in integration.send_serviceops for reprocessing
-- ============================================================================

-- Step 1: Delete from service_ops tables (in dependency order to avoid FK violations)

-- Delete packet_decision (depends on packet)
DELETE FROM service_ops.packet_decision;

-- Delete validation_run (depends on packet)
DELETE FROM service_ops.validation_run;

-- Delete packet_document (depends on packet)
DELETE FROM service_ops.packet_document;

-- Delete packet (main table)
DELETE FROM service_ops.packet;

-- Delete integration_inbox (processing queue)
DELETE FROM service_ops.integration_inbox;

-- Step 2: Verify cleanup
SELECT 
    (SELECT COUNT(*) FROM service_ops.packet) as packet_count,
    (SELECT COUNT(*) FROM service_ops.packet_document) as document_count,
    (SELECT COUNT(*) FROM service_ops.integration_inbox) as inbox_count,
    (SELECT COUNT(*) FROM service_ops.validation_run) as validation_count,
    (SELECT COUNT(*) FROM service_ops.packet_decision) as decision_count,
    (SELECT COUNT(*) FROM integration.send_serviceops WHERE is_deleted = false) as messages_remaining;

-- Step 3: Show messages ready for processing
SELECT 
    message_id,
    decision_tracking_id,
    channel_type_id,
    created_at,
    payload->>'message_type' as message_type,
    CASE 
        WHEN channel_type_id = 1 THEN 'Portal'
        WHEN channel_type_id = 2 THEN 'Fax'
        WHEN channel_type_id = 3 THEN 'ESMD'
        ELSE 'Unknown'
    END as channel_name
FROM integration.send_serviceops
WHERE is_deleted = false
ORDER BY channel_type_id, created_at;

