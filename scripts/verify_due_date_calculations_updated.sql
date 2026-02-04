-- ============================================================================
-- Query 6.2: Verify due_date Calculations (UPDATED for Partial Matching)
-- ============================================================================
-- Purpose: Confirm due_date is calculated correctly
-- 
-- UPDATED: Now handles partial matching for submission_type values like:
--   - 'expedited-initial' -> Expedited (48 hours)
--   - 'standard-initial' -> Standard (72 hours)
--   - 'expedited-someother' -> Expedited (48 hours)
--   - 'standard-some other value' -> Standard (72 hours)
--
-- This matches the code logic that uses starts_with() for submission_type
-- ============================================================================

-- Verify due_date calculations with partial matching
SELECT
    channel_type_id,
    CASE channel_type_id
        WHEN 1 THEN 'Portal'
        WHEN 2 THEN 'Fax'
        WHEN 3 THEN 'ESMD'
    END as channel_name,
    submission_type,
    COUNT(*) as packet_count,
    -- Check if due_date = received_date + 48 hours for EXPEDITED (using partial matching)
    COUNT(CASE
        WHEN submission_type IS NOT NULL
        AND (
            -- Check if submission_type starts with any expedited keyword (case-insensitive)
            LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        )
        AND due_date = received_date + INTERVAL '48 hours'
        THEN 1
    END) as expedited_correct,
    -- Check if due_date = received_date + 72 hours for STANDARD (using partial matching)
    COUNT(CASE
        WHEN (
            submission_type IS NULL 
            OR (
                -- Check if submission_type starts with any standard keyword (case-insensitive)
                LOWER(TRIM(submission_type)) LIKE 'standard%'
                OR LOWER(TRIM(submission_type)) LIKE 'normal%'
                OR LOWER(TRIM(submission_type)) LIKE 'routine%'
                OR LOWER(TRIM(submission_type)) LIKE 'regular%'
            )
        )
        AND due_date = received_date + INTERVAL '72 hours'
        THEN 1
    END) as standard_correct,
    -- Count packets with unrecognized submission_type (should be NULL or have incorrect due_date)
    COUNT(CASE
        WHEN submission_type IS NOT NULL
        AND NOT (
            LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
            OR LOWER(TRIM(submission_type)) LIKE 'standard%'
            OR LOWER(TRIM(submission_type)) LIKE 'normal%'
            OR LOWER(TRIM(submission_type)) LIKE 'routine%'
            OR LOWER(TRIM(submission_type)) LIKE 'regular%'
        )
        THEN 1
    END) as unrecognized_count
FROM service_ops.packet
GROUP BY channel_type_id, submission_type
ORDER BY channel_type_id, submission_type;

-- ============================================================================
-- Additional Query: Show examples of submission_type values that need updating
-- ============================================================================

-- Find packets with submission_type values that have suffixes (like 'expedited-initial')
-- These should be normalized to 'Expedited' or 'Standard'
SELECT
    external_id,
    channel_type_id,
    CASE channel_type_id
        WHEN 1 THEN 'Portal'
        WHEN 2 THEN 'Fax'
        WHEN 3 THEN 'ESMD'
    END as channel_name,
    submission_type,
    received_date,
    due_date,
    -- Show what it should be normalized to
    CASE
        WHEN submission_type IS NOT NULL AND (
            LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        ) THEN 'Expedited'
        WHEN submission_type IS NOT NULL AND (
            LOWER(TRIM(submission_type)) LIKE 'standard%'
            OR LOWER(TRIM(submission_type)) LIKE 'normal%'
            OR LOWER(TRIM(submission_type)) LIKE 'routine%'
            OR LOWER(TRIM(submission_type)) LIKE 'regular%'
        ) THEN 'Standard'
        ELSE 'NULL (unrecognized - needs manual review)'
    END as should_be_normalized_to,
    -- Show expected due_date
    CASE
        WHEN submission_type IS NOT NULL AND (
            LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        ) THEN received_date + INTERVAL '48 hours'
        ELSE received_date + INTERVAL '72 hours'
    END as expected_due_date,
    -- Check if due_date is correct
    CASE
        WHEN submission_type IS NOT NULL AND (
            LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        ) AND due_date = received_date + INTERVAL '48 hours' THEN '✓ Correct'
        WHEN (submission_type IS NULL OR (
            LOWER(TRIM(submission_type)) LIKE 'standard%'
            OR LOWER(TRIM(submission_type)) LIKE 'normal%'
            OR LOWER(TRIM(submission_type)) LIKE 'routine%'
            OR LOWER(TRIM(submission_type)) LIKE 'regular%'
        )) AND due_date = received_date + INTERVAL '72 hours' THEN '✓ Correct'
        ELSE '✗ Incorrect'
    END as due_date_status
FROM service_ops.packet
WHERE submission_type IS NOT NULL
    AND submission_type != 'Expedited'
    AND submission_type != 'Standard'
ORDER BY channel_type_id, submission_type
LIMIT 50;  -- Show first 50 examples

-- ============================================================================
-- Update Query: Normalize submission_type values with suffixes
-- ============================================================================
-- This query will update old records to match the new partial matching logic
-- It normalizes values like 'expedited-initial' to 'Expedited' and 'standard-initial' to 'Standard'

-- STEP 1: Preview what will be updated (run this first to verify)
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

-- STEP 2: Update submission_type (only if preview looks correct)
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

-- STEP 3: Verify the update
-- Run the verification query at the top of this file again after the update

