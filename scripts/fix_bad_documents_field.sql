-- ============================================================================
-- Fix Bad Documents Field in integration.send_serviceops
-- 
-- Problem: Some records have payload->'documents' as a scalar instead of an array
-- This causes: "cannot get array length of a scalar" error when polling
-- 
-- This script:
-- 1. Identifies records with bad documents field
-- 2. Shows what the bad records look like
-- 3. Provides options to fix them
-- ============================================================================

-- ============================================================================
-- STEP 1: Identify records with bad documents field
-- ============================================================================

-- Find records where documents is NOT an array (or is null)
SELECT 
    message_id,
    decision_tracking_id,
    channel_type_id,
    created_at,
    jsonb_typeof(payload->'documents') as documents_type,
    payload->'documents' as documents_value,
    CASE 
        WHEN jsonb_typeof(payload->'documents') = 'array' THEN 'OK'
        WHEN jsonb_typeof(payload->'documents') = 'null' THEN 'MISSING'
        ELSE 'BAD - Not an array'
    END as status
FROM integration.send_serviceops
WHERE is_deleted = false
    AND (
        jsonb_typeof(payload->'documents') != 'array'
        OR payload->'documents' IS NULL
    )
ORDER BY created_at DESC
LIMIT 50;

-- Count by type
SELECT 
    jsonb_typeof(payload->'documents') as documents_type,
    COUNT(*) as count
FROM integration.send_serviceops
WHERE is_deleted = false
GROUP BY jsonb_typeof(payload->'documents')
ORDER BY count DESC;

-- ============================================================================
-- STEP 2: Check if documents field exists at all
-- ============================================================================

-- Find records where documents field doesn't exist or is in wrong location
SELECT 
    message_id,
    decision_tracking_id,
    payload ? 'documents' as has_documents_at_root,
    payload->'ingest_data' ? 'raw_payload' as has_ingest_data,
    payload->'ingest_data'->'raw_payload' ? 'documents' as has_documents_in_ingest,
    jsonb_typeof(payload->'documents') as root_documents_type,
    jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') as ingest_documents_type
FROM integration.send_serviceops
WHERE is_deleted = false
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    )
ORDER BY created_at DESC
LIMIT 20;

-- ============================================================================
-- STEP 3: Sample of bad records (to understand the structure)
-- ============================================================================

-- Show full payload structure for a few bad records
SELECT 
    message_id,
    decision_tracking_id,
    payload
FROM integration.send_serviceops
WHERE is_deleted = false
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    )
ORDER BY created_at DESC
LIMIT 5;

-- ============================================================================
-- STEP 4: Fix Options (choose one based on your data structure)
-- ============================================================================

-- OPTION A: If documents is a scalar/null and should be an empty array
-- Uncomment and run if documents should be an empty array:
/*
UPDATE integration.send_serviceops
SET payload = jsonb_set(
    payload,
    '{documents}',
    '[]'::jsonb,
    true
)
WHERE is_deleted = false
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    );
*/

-- OPTION B: If documents is a scalar and should be wrapped in an array
-- Uncomment and run if documents should be wrapped:
/*
UPDATE integration.send_serviceops
SET payload = jsonb_set(
    payload,
    '{documents}',
    jsonb_build_array(payload->'documents'),
    true
)
WHERE is_deleted = false
    AND jsonb_typeof(payload->'documents') != 'array'
    AND payload->'documents' IS NOT NULL
    AND jsonb_typeof(payload->'documents') != 'null';
*/

-- OPTION C: If documents exists in ingest_data.raw_payload and should be moved to root
-- Uncomment and run if documents should be moved from ingest_data:
/*
UPDATE integration.send_serviceops
SET payload = jsonb_set(
    payload,
    '{documents}',
    COALESCE(
        payload->'ingest_data'->'raw_payload'->'documents',
        '[]'::jsonb
    ),
    true
)
WHERE is_deleted = false
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    )
    AND payload->'ingest_data'->'raw_payload'->'documents' IS NOT NULL
    AND jsonb_typeof(payload->'ingest_data'->'raw_payload'->'documents') = 'array';
*/

-- OPTION D: Mark bad records as deleted (if they can't be fixed)
-- Uncomment and run if bad records should be skipped:
/*
UPDATE integration.send_serviceops
SET is_deleted = true
WHERE is_deleted = false
    AND (
        payload->'documents' IS NULL
        OR jsonb_typeof(payload->'documents') != 'array'
    )
    AND payload->>'message_type' != 'ingest_file_package';
*/

-- ============================================================================
-- STEP 5: Verify fix
-- ============================================================================

-- After running a fix, verify all records have proper documents array
SELECT 
    COUNT(*) as total_records,
    COUNT(*) FILTER (WHERE jsonb_typeof(payload->'documents') = 'array') as has_array,
    COUNT(*) FILTER (WHERE jsonb_typeof(payload->'documents') != 'array' OR payload->'documents' IS NULL) as still_bad
FROM integration.send_serviceops
WHERE is_deleted = false;

-- ============================================================================
-- NOTES:
-- ============================================================================
-- 1. Run STEP 1 first to see what types of bad records you have
-- 2. Run STEP 2 to understand the data structure
-- 3. Run STEP 3 to see sample payloads
-- 4. Choose the appropriate fix from STEP 4 based on your data
-- 5. Run STEP 5 to verify the fix worked
-- 
-- IMPORTANT: Test on a small subset first before running on all 400 records!

