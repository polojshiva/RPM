-- ============================================================================
-- Query 6.2: Verify due_date Calculations (UPDATED)
-- ============================================================================
-- FIXED: Now uses partial matching (LIKE) instead of exact matching (IN)
-- This handles values like 'expedited-initial', 'standard-initial', etc.
-- ============================================================================

SELECT
    channel_type_id,
    CASE channel_type_id
        WHEN 1 THEN 'Portal'
        WHEN 2 THEN 'Fax'
        WHEN 3 THEN 'ESMD'
    END as channel_name,
    submission_type,
    COUNT(*) as packet_count,
    -- Check if due_date = received_date + 48 hours for EXPEDITED
    -- UPDATED: Uses LIKE for partial matching (handles 'expedited-initial', etc.)
    COUNT(CASE
        WHEN submission_type IS NOT NULL
        AND (
            LOWER(TRIM(submission_type)) LIKE 'expedited%'
            OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
            OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
            OR LOWER(TRIM(submission_type)) LIKE 'rush%'
        )
        AND due_date = received_date + INTERVAL '48 hours'
        THEN 1
    END) as expedited_correct,
    -- Check if due_date = received_date + 72 hours for STANDARD
    -- UPDATED: Uses LIKE for partial matching (handles 'standard-initial', etc.)
    COUNT(CASE
        WHEN (
            submission_type IS NULL 
            OR LOWER(TRIM(submission_type)) LIKE 'standard%'
            OR LOWER(TRIM(submission_type)) LIKE 'normal%'
            OR LOWER(TRIM(submission_type)) LIKE 'routine%'
            OR LOWER(TRIM(submission_type)) LIKE 'regular%'
        )
        AND due_date = received_date + INTERVAL '72 hours'
        THEN 1
    END) as standard_correct
FROM service_ops.packet
GROUP BY channel_type_id, submission_type
ORDER BY channel_type_id, submission_type;

