-- ============================================================================
-- UPDATE Query: Normalize submission_type values with suffixes
-- ============================================================================
-- Purpose: Update old records to normalize submission_type values like:
--   - 'expedited-initial' -> 'Expedited'
--   - 'standard-initial' -> 'Standard'
--   - 'expedited-someother' -> 'Expedited'
--   - 'standard-some other value' -> 'Standard'
--
-- This matches the new code logic that uses partial matching (starts with)
-- ============================================================================

-- STEP 1: PREVIEW what will be updated (run this first!)
SELECT
    packet_id,
    external_id,
    submission_type as current_value,
    CASE
        WHEN LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        THEN 'Expedited'
        WHEN LOWER(TRIM(submission_type)) LIKE 'standard%'
            OR LOWER(TRIM(submission_type)) LIKE 'normal%'
            OR LOWER(TRIM(submission_type)) LIKE 'routine%'
            OR LOWER(TRIM(submission_type)) LIKE 'regular%'
        THEN 'Standard'
        ELSE submission_type  -- Keep unrecognized values as-is (for manual review)
    END as new_value,
    received_date,
    due_date as current_due_date,
    CASE
        WHEN LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        THEN received_date + INTERVAL '48 hours'
        ELSE received_date + INTERVAL '72 hours'
    END as new_due_date
FROM service_ops.packet
WHERE submission_type IS NOT NULL
    AND submission_type != 'Expedited'
    AND submission_type != 'Standard'
ORDER BY external_id;

-- STEP 2: UPDATE submission_type and due_date (only if preview looks correct)
-- Uncomment and run this after verifying the preview:
/*
UPDATE service_ops.packet
SET 
    submission_type = CASE
        WHEN LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        THEN 'Expedited'
        WHEN LOWER(TRIM(submission_type)) LIKE 'standard%'
            OR LOWER(TRIM(submission_type)) LIKE 'normal%'
            OR LOWER(TRIM(submission_type)) LIKE 'routine%'
            OR LOWER(TRIM(submission_type)) LIKE 'regular%'
        THEN 'Standard'
        ELSE submission_type  -- Keep unrecognized values as-is (for manual review)
    END,
    due_date = CASE
        WHEN LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        THEN received_date + INTERVAL '48 hours'
        ELSE received_date + INTERVAL '72 hours'
    END,
    updated_at = NOW()
WHERE submission_type IS NOT NULL
    AND submission_type != 'Expedited'
    AND submission_type != 'Standard';
*/

-- STEP 3: VERIFY the update
-- Run Query 6.2 (verify_due_date_calculations_updated.sql) again after the update

