-- ============================================================================
-- SQL Script to Repopulate packet.received_date with Raw Timestamps
-- ============================================================================
-- Purpose: Update existing packets that have received_date normalized to midnight
--          with raw timestamps extracted from original payloads in integration.send_serviceops
--
-- This script:
-- 1. Finds packets with received_date at midnight (00:00:00)
-- 2. Extracts submission date from payload based on channel_type_id
-- 3. Updates packet.received_date with raw timestamp
--
-- IMPORTANT: Run this in a transaction and review before committing!
-- ============================================================================

-- STEP 1: Preview what will be updated (run this first!)
-- ============================================================================
SELECT 
    p.packet_id,
    p.external_id,
    p.decision_tracking_id,
    p.received_date as current_received_date,
    p.channel_type_id,
    CASE 
        WHEN p.channel_type_id = 1 THEN 'Portal'
        WHEN p.channel_type_id = 2 THEN 'Fax'
        WHEN p.channel_type_id = 3 THEN 'ESMD'
        ELSE 'Unknown'
    END as channel_type,
    EXTRACT(HOUR FROM p.received_date) as current_hour,
    EXTRACT(MINUTE FROM p.received_date) as current_minute,
    EXTRACT(SECOND FROM p.received_date) as current_second,
    -- Extract submission date from payload based on channel type
    CASE 
        -- ESMD (3): payload.submission_metadata.creationTime
        WHEN p.channel_type_id = 3 THEN 
            (s.payload->'submission_metadata'->>'creationTime')::text
        -- Portal (1): payload.ocr.fields["Submitted Date"].value
        WHEN p.channel_type_id = 1 THEN 
            (s.payload->'ocr'->'fields'->'Submitted Date'->>'value')::text
        -- Fax (2): payload.submission_metadata.creationTime (or extracted_fields)
        WHEN p.channel_type_id = 2 THEN 
            COALESCE(
                (s.payload->'submission_metadata'->>'creationTime')::text,
                (s.payload->'extracted_fields'->'fields'->'Submitted Date'->>'value')::text
            )
        ELSE NULL
    END as extracted_date_string,
    s.created_at as message_created_at,
    -- Calculate new received_date (will be parsed in Python script)
    -- For SQL, we can use message.created_at as fallback
    COALESCE(
        CASE 
            WHEN p.channel_type_id = 3 THEN 
                (s.payload->'submission_metadata'->>'creationTime')::timestamptz
            WHEN p.channel_type_id = 1 THEN 
                (s.payload->'ocr'->'fields'->'Submitted Date'->>'value')::timestamptz
            WHEN p.channel_type_id = 2 THEN 
                COALESCE(
                    (s.payload->'submission_metadata'->>'creationTime')::timestamptz,
                    (s.payload->'extracted_fields'->'fields'->'Submitted Date'->>'value')::timestamptz
                )
            ELSE NULL
        END,
        s.created_at
    ) as new_received_date
FROM service_ops.packet p
INNER JOIN integration.send_serviceops s
    ON p.decision_tracking_id::text = s.decision_tracking_id::text
WHERE 
    -- Only process packets with midnight times (normalized)
    (EXTRACT(HOUR FROM p.received_date) = 0 
     AND EXTRACT(MINUTE FROM p.received_date) = 0 
     AND EXTRACT(SECOND FROM p.received_date) = 0)
    AND s.is_deleted = false
    AND s.payload IS NOT NULL
ORDER BY p.packet_id
LIMIT 10;  -- Preview first 10

-- ============================================================================
-- STEP 2: Update packets with raw timestamps
-- ============================================================================
-- WARNING: This will update all matching packets!
-- Review the preview query above before running this.
-- ============================================================================

BEGIN;

-- Update using extracted date from payload (with fallback to message.created_at)
UPDATE service_ops.packet p
SET 
    received_date = COALESCE(
        CASE 
            -- ESMD (3): payload.submission_metadata.creationTime
            WHEN p.channel_type_id = 3 THEN 
                (s.payload->'submission_metadata'->>'creationTime')::timestamptz
            -- Portal (1): payload.ocr.fields["Submitted Date"].value
            WHEN p.channel_type_id = 1 THEN 
                (s.payload->'ocr'->'fields'->'Submitted Date'->>'value')::timestamptz
            -- Fax (2): payload.submission_metadata.creationTime (or extracted_fields)
            WHEN p.channel_type_id = 2 THEN 
                COALESCE(
                    (s.payload->'submission_metadata'->>'creationTime')::timestamptz,
                    (s.payload->'extracted_fields'->'fields'->'Submitted Date'->>'value')::timestamptz
                )
            ELSE NULL
        END,
        s.created_at
    ),
    updated_at = NOW()
FROM integration.send_serviceops s
WHERE 
    p.decision_tracking_id::text = s.decision_tracking_id::text
    -- Only update packets with midnight times (normalized)
    AND (EXTRACT(HOUR FROM p.received_date) = 0 
         AND EXTRACT(MINUTE FROM p.received_date) = 0 
         AND EXTRACT(SECOND FROM p.received_date) = 0)
    AND s.is_deleted = false
    AND s.payload IS NOT NULL
    -- Only update if new date is different and has non-midnight time
    AND (
        COALESCE(
            CASE 
                WHEN p.channel_type_id = 3 THEN 
                    (s.payload->'submission_metadata'->>'creationTime')::timestamptz
                WHEN p.channel_type_id = 1 THEN 
                    (s.payload->'ocr'->'fields'->'Submitted Date'->>'value')::timestamptz
                WHEN p.channel_type_id = 2 THEN 
                    COALESCE(
                        (s.payload->'submission_metadata'->>'creationTime')::timestamptz,
                        (s.payload->'extracted_fields'->'fields'->'Submitted Date'->>'value')::timestamptz
                    )
                ELSE NULL
            END,
            s.created_at
        ) IS NOT NULL
        AND (
            EXTRACT(HOUR FROM COALESCE(
                CASE 
                    WHEN p.channel_type_id = 3 THEN 
                        (s.payload->'submission_metadata'->>'creationTime')::timestamptz
                    WHEN p.channel_type_id = 1 THEN 
                        (s.payload->'ocr'->'fields'->'Submitted Date'->>'value')::timestamptz
                    WHEN p.channel_type_id = 2 THEN 
                        COALESCE(
                            (s.payload->'submission_metadata'->>'creationTime')::timestamptz,
                            (s.payload->'extracted_fields'->'fields'->'Submitted Date'->>'value')::timestamptz
                        )
                    ELSE NULL
                END,
                s.created_at
            )) != 0
            OR EXTRACT(MINUTE FROM COALESCE(
                CASE 
                    WHEN p.channel_type_id = 3 THEN 
                        (s.payload->'submission_metadata'->>'creationTime')::timestamptz
                    WHEN p.channel_type_id = 1 THEN 
                        (s.payload->'ocr'->'fields'->'Submitted Date'->>'value')::timestamptz
                    WHEN p.channel_type_id = 2 THEN 
                        COALESCE(
                            (s.payload->'submission_metadata'->>'creationTime')::timestamptz,
                            (s.payload->'extracted_fields'->'fields'->'Submitted Date'->>'value')::timestamptz
                        )
                    ELSE NULL
                END,
                s.created_at
            )) != 0
        )
    );

-- Check how many rows were updated
SELECT COUNT(*) as updated_count
FROM service_ops.packet p
INNER JOIN integration.send_serviceops s
    ON p.decision_tracking_id::text = s.decision_tracking_id::text
WHERE 
    (EXTRACT(HOUR FROM p.received_date) = 0 
     AND EXTRACT(MINUTE FROM p.received_date) = 0 
     AND EXTRACT(SECOND FROM p.received_date) = 0)
    AND s.is_deleted = false
    AND s.payload IS NOT NULL;

-- Review the changes before committing
SELECT 
    p.packet_id,
    p.external_id,
    p.received_date,
    EXTRACT(HOUR FROM p.received_date) as hour,
    EXTRACT(MINUTE FROM p.received_date) as minute,
    EXTRACT(SECOND FROM p.received_date) as second
FROM service_ops.packet p
INNER JOIN integration.send_serviceops s
    ON p.decision_tracking_id::text = s.decision_tracking_id::text
WHERE 
    (EXTRACT(HOUR FROM p.received_date) = 0 
     AND EXTRACT(MINUTE FROM p.received_date) = 0 
     AND EXTRACT(SECOND FROM p.received_date) = 0)
    AND s.is_deleted = false
    AND s.payload IS NOT NULL
LIMIT 10;

-- If everything looks good, commit:
-- COMMIT;

-- If something is wrong, rollback:
-- ROLLBACK;
