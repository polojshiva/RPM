-- Manual Test: Insert Messages into Inbox
-- Purpose: Test the inbox system with real messages from integration.send_serviceops
-- Use this to verify the system works before waiting for the poller

-- ============================================================================
-- Step 1: View messages that will be inserted
-- ============================================================================
SELECT 
    message_id,
    decision_tracking_id,
    payload->>'message_type' as message_type,
    created_at,
    is_deleted
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' = 'ingest_file_package'
ORDER BY created_at ASC, message_id ASC
LIMIT 10;

-- ============================================================================
-- Step 2: Insert first 5 messages into inbox (idempotent)
-- ============================================================================
-- This simulates what the poller does
INSERT INTO service_ops.integration_inbox (
    message_id,
    decision_tracking_id,
    message_type,
    source_created_at,
    status
)
SELECT 
    message_id,
    decision_tracking_id,
    payload->>'message_type',
    created_at,
    'NEW'
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' = 'ingest_file_package'
ORDER BY created_at ASC, message_id ASC
LIMIT 5
ON CONFLICT (decision_tracking_id, message_type) DO NOTHING
RETURNING 
    inbox_id,
    message_id,
    decision_tracking_id,
    message_type,
    status,
    created_at;

-- ============================================================================
-- Step 3: Check inbox after insert
-- ============================================================================
SELECT 
    inbox_id,
    message_id,
    decision_tracking_id,
    message_type,
    status,
    attempt_count,
    next_attempt_at,
    created_at
FROM service_ops.integration_inbox
ORDER BY created_at DESC;

-- ============================================================================
-- Step 4: Check status summary
-- ============================================================================
SELECT 
    status,
    COUNT(*) as count,
    MIN(created_at) as oldest,
    MAX(created_at) as newest
FROM service_ops.integration_inbox
GROUP BY status
ORDER BY status;

-- ============================================================================
-- Step 5: Test claim job (simulate worker)
-- ============================================================================
-- This will claim one job and mark it as PROCESSING
WITH claimed AS (
    UPDATE service_ops.integration_inbox
    SET 
        status = 'PROCESSING',
        locked_by = 'test-worker-manual',
        locked_at = NOW(),
        attempt_count = attempt_count + 1,
        updated_at = NOW()
    WHERE inbox_id = (
        SELECT inbox_id
        FROM service_ops.integration_inbox
        WHERE status = 'NEW'
            AND next_attempt_at <= NOW()
        ORDER BY source_created_at ASC, message_id ASC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING *
)
SELECT 
    inbox_id,
    message_id,
    decision_tracking_id,
    status,
    attempt_count,
    locked_by,
    locked_at
FROM claimed;

-- ============================================================================
-- Step 6: View claimed job
-- ============================================================================
SELECT 
    inbox_id,
    message_id,
    decision_tracking_id,
    status,
    attempt_count,
    locked_by,
    locked_at
FROM service_ops.integration_inbox
WHERE status = 'PROCESSING';

-- ============================================================================
-- Step 7: Test mark as done (after processing)
-- ============================================================================
-- Uncomment and run after you've "processed" the job
/*
UPDATE service_ops.integration_inbox
SET 
    status = 'DONE',
    updated_at = NOW(),
    locked_by = NULL,
    locked_at = NULL,
    last_error = NULL
WHERE inbox_id = :inbox_id  -- Replace with actual inbox_id from Step 5
RETURNING inbox_id, status, updated_at;
*/

-- ============================================================================
-- Step 8: Test mark as failed (with retry)
-- ============================================================================
-- Uncomment to test failure handling
/*
UPDATE service_ops.integration_inbox
SET 
    status = CASE 
        WHEN attempt_count >= 5 THEN 'DEAD'
        ELSE 'FAILED'
    END,
    last_error = 'Test error message',
    next_attempt_at = CASE 
        WHEN attempt_count = 0 THEN NOW() + INTERVAL '1 minute'
        WHEN attempt_count = 1 THEN NOW() + INTERVAL '5 minutes'
        WHEN attempt_count = 2 THEN NOW() + INTERVAL '15 minutes'
        WHEN attempt_count = 3 THEN NOW() + INTERVAL '1 hour'
        WHEN attempt_count = 4 THEN NOW() + INTERVAL '6 hours'
        ELSE NOW() + INTERVAL '24 hours'
    END,
    locked_by = NULL,
    locked_at = NULL,
    updated_at = NOW()
WHERE inbox_id = :inbox_id  -- Replace with actual inbox_id
RETURNING inbox_id, status, attempt_count, next_attempt_at, last_error;
*/

-- ============================================================================
-- Step 9: Clean up test data (optional)
-- ============================================================================
-- Uncomment to remove test records
/*
DELETE FROM service_ops.integration_inbox
WHERE locked_by = 'test-worker-manual'
   OR status IN ('DONE', 'FAILED', 'DEAD');
*/

