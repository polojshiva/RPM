-- ============================================================================
-- Cleanup Script for Decision Tracking ID: 16d2c371-7d2d-48a0-8e0e-267fce7a3fb5
-- 
-- Purpose: Clean all database records for this decision_tracking_id
-- Blob storage cleanup: Manual (user will handle separately)
-- ============================================================================

-- ============================================================================
-- STEP 1: Get Information Before Deletion (for reference)
-- ============================================================================

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
WHERE p.decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5';

-- ============================================================================
-- STEP 2: Clean Database Records (in dependency order)
-- ============================================================================

BEGIN;

-- 2.1: Delete decisions (child of packet and packet_document)
DELETE FROM service_ops.packet_decision 
WHERE packet_id IN (
    SELECT packet_id FROM service_ops.packet 
    WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5'
);

-- 2.2: Delete validation runs (child of packet and packet_document)
DELETE FROM service_ops.validation_run 
WHERE packet_id IN (
    SELECT packet_id FROM service_ops.packet 
    WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5'
);

-- 2.3: Delete document records (child of packet)
DELETE FROM service_ops.packet_document 
WHERE packet_id IN (
    SELECT packet_id FROM service_ops.packet 
    WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5'
);

-- 2.4: Delete packet record
DELETE FROM service_ops.packet 
WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5';

-- 2.5: Delete from integration inbox (processing queue)
DELETE FROM service_ops.integration_inbox 
WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5';

COMMIT;

-- ============================================================================
-- STEP 3: Verify Cleanup
-- ============================================================================

SELECT 
    'packet' as table_name,
    COUNT(*) as remaining_count
FROM service_ops.packet 
WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5'

UNION ALL

SELECT 
    'packet_document' as table_name,
    COUNT(*) as remaining_count
FROM service_ops.packet_document pd
JOIN service_ops.packet p ON pd.packet_id = p.packet_id
WHERE p.decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5'

UNION ALL

SELECT 
    'integration_inbox' as table_name,
    COUNT(*) as remaining_count
FROM service_ops.integration_inbox 
WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5'

UNION ALL

SELECT 
    'packet_decision' as table_name,
    COUNT(*) as remaining_count
FROM service_ops.packet_decision pd
JOIN service_ops.packet p ON pd.packet_id = p.packet_id
WHERE p.decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5'

UNION ALL

SELECT 
    'validation_run' as table_name,
    COUNT(*) as remaining_count
FROM service_ops.validation_run vr
JOIN service_ops.packet p ON vr.packet_id = p.packet_id
WHERE p.decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5';

-- ============================================================================
-- STEP 4: Check Source Table Status
-- ============================================================================

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
WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5'
ORDER BY created_at DESC;

-- ============================================================================
-- STEP 5: Prepare Source Table for Reprocessing (if needed)
-- ============================================================================
-- Uncomment and run if is_deleted = true and you want to reprocess:

-- UPDATE integration.send_serviceops
-- SET 
--     is_deleted = false,
--     created_at = NOW()
-- WHERE decision_tracking_id = '16d2c371-7d2d-48a0-8e0e-267fce7a3fb5';

