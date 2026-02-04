-- ============================================================================
-- Check Payload Structure for All Records
-- 
-- This script helps identify why some records process and others don't
-- ============================================================================

-- ============================================================================
-- STEP 1: Check which format each record uses
-- ============================================================================

SELECT 
    message_id,
    decision_tracking_id,
    created_at,
    -- Check for message_type
    payload->>'message_type' as message_type,
    -- Check for decision_tracking_id
    payload->>'decision_tracking_id' as decision_tracking_id,
    -- Check NEW FORMAT (root level documents)
    CASE 
        WHEN payload->'documents' IS NULL THEN 'NULL'
        WHEN jsonb_typeof(payload->'documents') = 'array' THEN 'ARRAY (NEW FORMAT)'
        ELSE 'SCALAR/OTHER (BAD)'
    END as root_documents_status,
    CASE 
        WHEN jsonb_typeof(payload->'documents') = 'array' 
        THEN jsonb_array_length(payload->'documents')
        ELSE NULL
    END as root_documents_count,
    -- Check OLD FORMAT (nested documents)
    CASE 
        WHEN payload->'ingest_data'->'raw_payload'->'documents' IS NULL THEN 'NULL'
        WHEN jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') = 'array' THEN 'ARRAY (OLD FORMAT)'
        ELSE 'SCALAR/OTHER (BAD)'
    END as nested_documents_status,
    CASE 
        WHEN jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') = 'array'
        THEN jsonb_array_length(payload->'ingest_data'->'raw_payload'->'documents')
        ELSE NULL
    END as nested_documents_count,
    -- Overall status
    CASE 
        WHEN payload->>'message_type' = 'ingest_file_package' THEN 'OK (has message_type)'
        WHEN jsonb_typeof(payload->'documents') = 'array' AND jsonb_array_length(payload->'documents') > 0 THEN 'OK (NEW FORMAT)'
        WHEN jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') = 'array' AND jsonb_array_length(payload->'ingest_data'->'raw_payload'->'documents') > 0 THEN 'OK (OLD FORMAT)'
        ELSE 'FAILED - No valid documents found'
    END as processing_status
FROM integration.send_serviceops
WHERE is_deleted = false
ORDER BY created_at DESC
LIMIT 50;

-- ============================================================================
-- STEP 2: Summary statistics
-- ============================================================================

SELECT 
    'Total Records' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false

UNION ALL

SELECT 
    'Has message_type = ingest_file_package' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' = 'ingest_file_package'

UNION ALL

SELECT 
    'Has documents at root (NEW FORMAT)' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND jsonb_typeof(payload->'documents') = 'array'
    AND jsonb_array_length(payload->'documents') > 0

UNION ALL

SELECT 
    'Has documents in ingest_data (OLD FORMAT)' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') = 'array'
    AND jsonb_array_length(payload->'ingest_data'->'raw_payload'->'documents') > 0

UNION ALL

SELECT 
    'FAILED - No valid documents' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' != 'ingest_file_package'
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
        OR jsonb_array_length(payload->'documents') = 0
    )
    AND (
        payload->'ingest_data'->'raw_payload'->'documents' IS NULL
        OR jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') != 'array'
        OR jsonb_array_length(payload->'ingest_data'->'raw_payload'->'documents') = 0
    );

-- ============================================================================
-- STEP 3: Find records that will FAIL with current query
-- ============================================================================

SELECT 
    message_id,
    decision_tracking_id,
    created_at,
    payload->>'message_type' as message_type,
    jsonb_typeof(payload->'documents') as root_documents_type,
    jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') as nested_documents_type,
    payload->'documents' as root_documents_sample,
    payload->'ingest_data'->'raw_payload'->'documents' as nested_documents_sample
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' != 'ingest_file_package'
    AND (
        -- No valid documents in either location
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
        OR jsonb_array_length(payload->'documents') = 0
    )
    AND (
        payload->'ingest_data'->'raw_payload'->'documents' IS NULL
        OR jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') != 'array'
        OR jsonb_array_length(payload->'ingest_data'->'raw_payload'->'documents') = 0
    )
ORDER BY created_at DESC
LIMIT 20;

