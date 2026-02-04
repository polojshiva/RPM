-- ============================================================================
-- Find Bad Records Causing Processing Failure
-- 
-- Purpose: Find records that would cause "cannot get array length of a scalar" error
-- This helps identify if ONE bad record blocked all 400 records from processing
-- ============================================================================

-- ============================================================================
-- QUERY 1: Find records with BAD documents field (scalar/null instead of array)
-- This is the EXACT error condition
-- ============================================================================

SELECT 
    message_id,
    decision_tracking_id,
    created_at,
    channel_type_id,
    -- Check what type documents actually is
    jsonb_typeof(payload->'documents') as documents_type,
    -- Show the actual value (truncated for readability)
    LEFT(payload->'documents'::text, 100) as documents_value_preview,
    -- Check if it would match the query conditions
    payload->>'message_type' as message_type,
    payload->>'decision_tracking_id' as decision_tracking_id,
    -- Status
    CASE 
        WHEN payload->>'message_type' = 'ingest_file_package' THEN 'OK - Has message_type'
        WHEN jsonb_typeof(payload->'documents') = 'array' THEN 'OK - Has array'
        WHEN jsonb_typeof(payload->'documents') = 'null' THEN 'BAD - NULL'
        WHEN jsonb_typeof(payload->'documents') = 'string' THEN 'BAD - String (scalar)'
        WHEN jsonb_typeof(payload->'documents') = 'object' THEN 'BAD - Object (scalar)'
        WHEN jsonb_typeof(payload->'documents') IS NULL THEN 'BAD - Missing field'
        ELSE 'BAD - Unknown type: ' || jsonb_typeof(payload->'documents')
    END as error_reason,
    -- Would this cause the error?
    CASE 
        WHEN payload->>'message_type' = 'ingest_file_package' THEN false
        WHEN jsonb_typeof(payload->'documents') = 'array' THEN false
        WHEN payload->>'decision_tracking_id' IS NOT NULL 
            AND payload->'documents' IS NOT NULL 
            AND jsonb_typeof(payload->'documents') != 'array' THEN true  -- THIS CAUSES THE ERROR
        ELSE false
    END as would_cause_error
FROM integration.send_serviceops
WHERE is_deleted = false
    AND (
        -- Records that would match the query but have bad documents field
        (
            payload->>'decision_tracking_id' IS NOT NULL
            AND payload->'documents' IS NOT NULL
            AND jsonb_typeof(payload->'documents') != 'array'
        )
        OR
        -- Records with null documents
        (
            payload->>'decision_tracking_id' IS NOT NULL
            AND payload->'documents' IS NULL
        )
        OR
        -- Records with missing documents field entirely
        (
            payload->>'decision_tracking_id' IS NOT NULL
            AND payload ? 'documents' = false
        )
    )
ORDER BY created_at ASC, message_id ASC;

-- ============================================================================
-- QUERY 2: Count how many bad records exist
-- ============================================================================

SELECT 
    'Total records' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false

UNION ALL

SELECT 
    'Records that would CAUSE ERROR' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' != 'ingest_file_package'
    AND payload->>'decision_tracking_id' IS NOT NULL
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    )

UNION ALL

SELECT 
    'Records with documents = NULL' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->'documents' IS NULL

UNION ALL

SELECT 
    'Records with documents = scalar (string)' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND jsonb_typeof(payload->'documents') = 'string'

UNION ALL

SELECT 
    'Records with documents = scalar (object)' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND jsonb_typeof(payload->'documents') = 'object'

UNION ALL

SELECT 
    'Records with documents = array (GOOD)' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND jsonb_typeof(payload->'documents') = 'array'

UNION ALL

SELECT 
    'Records with message_type = ingest_file_package (OK)' as category,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' = 'ingest_file_package';

-- ============================================================================
-- QUERY 3: Find the FIRST bad record (the one that blocked everything)
-- ============================================================================

SELECT 
    'FIRST BAD RECORD (blocked all processing)' as note,
    message_id,
    decision_tracking_id,
    created_at,
    channel_type_id,
    jsonb_typeof(payload->'documents') as documents_type,
    payload->>'message_type' as message_type,
    LEFT(payload->'documents'::text, 200) as documents_value_preview
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' != 'ingest_file_package'
    AND payload->>'decision_tracking_id' IS NOT NULL
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    )
ORDER BY created_at ASC, message_id ASC
LIMIT 1;

-- ============================================================================
-- QUERY 4: Show sample of bad records with full payload structure
-- ============================================================================

SELECT 
    message_id,
    decision_tracking_id,
    created_at,
    jsonb_typeof(payload->'documents') as documents_type,
    -- Show the full payload structure (for debugging)
    payload
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' != 'ingest_file_package'
    AND payload->>'decision_tracking_id' IS NOT NULL
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    )
ORDER BY created_at ASC, message_id ASC
LIMIT 5;

-- ============================================================================
-- QUERY 5: Check if documents exists in old format location
-- ============================================================================

SELECT 
    message_id,
    decision_tracking_id,
    created_at,
    'Root documents: ' || COALESCE(jsonb_typeof(payload->'documents'), 'MISSING') as root_status,
    'Nested documents: ' || COALESCE(jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents'), 'MISSING') as nested_status,
    CASE 
        WHEN jsonb_typeof(payload->'documents') = 'array' THEN 'OK - Has at root'
        WHEN jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') = 'array' THEN 'OK - Has in nested location'
        ELSE 'BAD - No valid documents found'
    END as status
FROM integration.send_serviceops
WHERE is_deleted = false
    AND payload->>'message_type' != 'ingest_file_package'
    AND payload->>'decision_tracking_id' IS NOT NULL
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    )
ORDER BY created_at ASC, message_id ASC
LIMIT 10;

