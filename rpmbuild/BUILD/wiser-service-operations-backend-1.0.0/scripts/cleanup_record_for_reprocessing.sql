-- ============================================================================
-- Cleanup Script for Reprocessing a Single Record
-- 
-- Purpose: Clean all database records and provide blob storage paths
--          for a specific decision_tracking_id to allow clean reprocessing
--
-- Usage: Replace <YOUR_DECISION_TRACKING_ID> with your actual UUID
-- ============================================================================

-- ============================================================================
-- STEP 1: Get Information Before Deletion (for blob storage cleanup)
-- ============================================================================

-- Get packet_id, blob paths, and related information
SELECT 
    p.packet_id,
    p.decision_tracking_id,
    p.external_id as packet_external_id,
    pd.packet_document_id,
    pd.external_id as document_external_id,
    pd.consolidated_blob_path,
    pd.pages_metadata,
    pd.split_status,
    pd.ocr_status,
    (SELECT COUNT(*) FROM service_ops.packet_decision WHERE packet_id = p.packet_id) as decision_count,
    (SELECT COUNT(*) FROM service_ops.validation_run WHERE packet_id = p.packet_id) as validation_count
FROM service_ops.packet p
LEFT JOIN service_ops.packet_document pd ON p.packet_id = pd.packet_id
WHERE p.decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';

-- ============================================================================
-- STEP 2: Clean Database Records (in dependency order)
-- ============================================================================

BEGIN;

-- 2.1: Delete decisions (child of packet and packet_document)
DELETE FROM service_ops.packet_decision 
WHERE packet_id IN (
    SELECT packet_id FROM service_ops.packet 
    WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>'
);

-- 2.2: Delete validation runs (child of packet and packet_document)
DELETE FROM service_ops.validation_run 
WHERE packet_id IN (
    SELECT packet_id FROM service_ops.packet 
    WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>'
);

-- 2.3: Delete document records (child of packet)
DELETE FROM service_ops.packet_document 
WHERE packet_id IN (
    SELECT packet_id FROM service_ops.packet 
    WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>'
);

-- 2.4: Delete packet record
DELETE FROM service_ops.packet 
WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';

-- 2.5: Delete from integration inbox (processing queue)
DELETE FROM service_ops.integration_inbox 
WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';

-- ============================================================================
-- STEP 3: Verify Cleanup
-- ============================================================================

DO $$
DECLARE
    v_packet_count INT;
    v_document_count INT;
    v_inbox_count INT;
    v_decision_count INT;
    v_validation_count INT;
BEGIN
    -- Check packet
    SELECT COUNT(*) INTO v_packet_count
    FROM service_ops.packet 
    WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';
    
    -- Check document
    SELECT COUNT(*) INTO v_document_count
    FROM service_ops.packet_document pd
    JOIN service_ops.packet p ON pd.packet_id = p.packet_id
    WHERE p.decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';
    
    -- Check inbox
    SELECT COUNT(*) INTO v_inbox_count
    FROM service_ops.integration_inbox 
    WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';
    
    -- Check decisions
    SELECT COUNT(*) INTO v_decision_count
    FROM service_ops.packet_decision pd
    JOIN service_ops.packet p ON pd.packet_id = p.packet_id
    WHERE p.decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';
    
    -- Check validations
    SELECT COUNT(*) INTO v_validation_count
    FROM service_ops.validation_run vr
    JOIN service_ops.packet p ON vr.packet_id = p.packet_id
    WHERE p.decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';
    
    -- Report results
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Cleanup Verification Results:';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Packet records: %', v_packet_count;
    RAISE NOTICE 'Document records: %', v_document_count;
    RAISE NOTICE 'Inbox records: %', v_inbox_count;
    RAISE NOTICE 'Decision records: %', v_decision_count;
    RAISE NOTICE 'Validation records: %', v_validation_count;
    RAISE NOTICE '========================================';
    
    IF v_packet_count = 0 AND v_document_count = 0 AND v_inbox_count = 0 
       AND v_decision_count = 0 AND v_validation_count = 0 THEN
        RAISE NOTICE '✓ SUCCESS: All database records cleaned';
    ELSE
        RAISE WARNING '⚠ WARNING: Cleanup incomplete!';
        RAISE WARNING '   Some records may still exist.';
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- STEP 4: Check Source Table Status
-- ============================================================================

-- Check if record exists in integration.send_serviceops
SELECT 
    message_id,
    decision_tracking_id,
    is_deleted,
    created_at,
    channel_type_id,
    CASE 
        WHEN channel_type_id = 1 THEN 'Genzeon Portal'
        WHEN channel_type_id = 2 THEN 'Genzeon Fax'
        WHEN channel_type_id = 3 THEN 'ESMD'
        ELSE 'Unknown'
    END as channel_name
FROM integration.send_serviceops
WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>'
ORDER BY created_at DESC;

-- ============================================================================
-- STEP 5: Prepare Source Table for Reprocessing (if needed)
-- ============================================================================

-- Uncomment and run if you need to ensure the record is ready to be picked up:
-- UPDATE integration.send_serviceops
-- SET 
--     is_deleted = false,
--     created_at = NOW()  -- Update timestamp to ensure it's picked up by poller
-- WHERE decision_tracking_id = '<YOUR_DECISION_TRACKING_ID>';

-- ============================================================================
-- NOTES:
-- ============================================================================
-- 1. After running this script, you need to manually clean blob storage:
--    - Delete consolidated PDF: Use consolidated_blob_path from Step 1
--    - Delete page PDFs: Extract paths from pages_metadata JSONB from Step 1
--
-- 2. Blob storage path structure:
--    service_ops_processing/YYYY/MM-DD/{decision_tracking_id}/
--        ├── packet_{packet_id}.pdf
--        └── packet_{packet_id}_pages/
--            ├── packet_{packet_id}_page_0001.pdf
--            └── ...
--
-- 3. The MessagePollerService will automatically:
--    - Poll integration.send_serviceops for records where is_deleted = false
--    - Insert into service_ops.integration_inbox (idempotent)
--    - Process through DocumentProcessor
--
-- 4. If the record doesn't exist in integration.send_serviceops, you'll need
--    to insert it manually with the correct payload structure.

