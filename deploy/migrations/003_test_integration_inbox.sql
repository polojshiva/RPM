-- Test Script for Integration Inbox
-- Purpose: Verify the inbox system works with sample data
-- Run this after migration to test the system

-- ============================================================================
-- Step 1: Check if there are any messages in integration.send_serviceops
-- ============================================================================
SELECT 
    COUNT(*) as total_messages,
    COUNT(*) FILTER (WHERE is_deleted = false) as active_messages,
    COUNT(*) FILTER (WHERE payload->>'message_type' = 'ingest_file_package') as ingest_file_package_messages
FROM integration.send_serviceops;

-- ============================================================================
-- Step 2: Check current watermark
-- ============================================================================
SELECT * FROM service_ops.integration_poll_watermark;

-- ============================================================================
-- Step 3: Check inbox status (should be empty initially)
-- ============================================================================
SELECT 
    status,
    COUNT(*) as count
FROM service_ops.integration_inbox
GROUP BY status;

-- ============================================================================
-- Step 4: View sample messages from integration.send_serviceops
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
ORDER BY created_at DESC
LIMIT 5;

-- ============================================================================
-- Step 5: Manual test - Insert a test message into inbox
-- ============================================================================
-- This simulates what the poller would do
-- Replace :message_id, :decision_tracking_id, :message_type, :source_created_at with actual values

-- Example (uncomment and modify with real values):
/*
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
    AND message_id = :message_id  -- Replace with actual message_id
ON CONFLICT (decision_tracking_id, message_type) DO NOTHING
RETURNING inbox_id, message_id, decision_tracking_id, status;
*/

-- ============================================================================
-- Step 6: Check inbox after manual insert
-- ============================================================================
SELECT 
    inbox_id,
    message_id,
    decision_tracking_id,
    message_type,
    status,
    attempt_count,
    created_at
FROM service_ops.integration_inbox
ORDER BY created_at DESC
LIMIT 10;

-- ============================================================================
-- Step 7: Test claim job (if you have NEW jobs)
-- ============================================================================
-- This simulates what a worker would do
/*
WITH claimed AS (
    UPDATE service_ops.integration_inbox
    SET 
        status = 'PROCESSING',
        locked_by = 'test-worker-123',
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
SELECT * FROM claimed;
*/

-- ============================================================================
-- Step 8: Verify the system is ready
-- ============================================================================
-- Expected results:
-- 1. integration_inbox: Empty (0 rows) - This is CORRECT until messages are polled
-- 2. integration_poll_watermark: 1 row with id=1 - This is CORRECT (initialized)

SELECT 
    'integration_inbox' as table_name,
    COUNT(*) as row_count,
    CASE 
        WHEN COUNT(*) = 0 THEN '✓ Empty (expected - will populate when poller runs)'
        ELSE 'Has ' || COUNT(*) || ' record(s)'
    END as status
FROM service_ops.integration_inbox

UNION ALL

SELECT 
    'integration_poll_watermark' as table_name,
    COUNT(*) as row_count,
    CASE 
        WHEN COUNT(*) = 1 THEN '✓ Initialized correctly'
        ELSE 'ERROR: Should have exactly 1 row'
    END as status
FROM service_ops.integration_poll_watermark;

