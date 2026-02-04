-- Cleanup script to reset state after ClinicalOps processing
-- This removes all processing that happened after synthetic ClinicalOps responses

BEGIN;

-- 1. Delete all ClinicalOps responses from send_serviceops
DELETE FROM service_ops.send_serviceops
WHERE payload->>'message_type' = 'CLINICAL_DECISION'
AND decision_tracking_id IN (
    'b1c2d3e4-5678-4abc-9def-234567890abc',
    'f7b17c23-fbe4-4ed3-b8d9-8e7ef8c44067'
);

-- 2. Delete all send_integration records for these packets
DELETE FROM service_ops.send_integration
WHERE decision_tracking_id IN (
    'b1c2d3e4-5678-4abc-9def-234567890abc',
    'f7b17c23-fbe4-4ed3-b8d9-8e7ef8c44067'
);

-- 3. Reset packet_decision records to the state before ClinicalOps processing
-- Keep only the first decision record (created when "Send to Clinical Ops" was clicked)
-- Delete all subsequent decision records (created by ClinicalOps processing)

-- For packet 1 (b1c2d3e4-5678-4abc-9def-234567890abc)
-- Keep the decision created when "Send to Clinical Ops" was clicked
-- Delete any duplicates (if any)

-- For packet 2 (f7b17c23-fbe4-4ed3-b8d9-8e7ef8c44067)
-- Keep only the decision created when "Send to Clinical Ops" was clicked
-- This should be the one with clinical_decision = 'PENDING' and created around 2026-01-14 00:44:50

DELETE FROM service_ops.packet_decision
WHERE packet_decision_id IN (
    SELECT pd.packet_decision_id
    FROM service_ops.packet_decision pd
    JOIN service_ops.packet p ON pd.packet_id = p.packet_id
    WHERE p.decision_tracking_id IN (
        'b1c2d3e4-5678-4abc-9def-234567890abc',
        'f7b17c23-fbe4-4ed3-b8d9-8e7ef8c44067'
    )
    AND pd.clinical_decision != 'PENDING'  -- Delete all non-PENDING clinical decisions
    OR (
        pd.clinical_decision = 'PENDING'
        AND pd.created_at > '2026-01-14 00:45:00'::timestamptz  -- Keep only the original PENDING
    )
);

-- 4. Reset packet status to "Pending - Clinical Review"
UPDATE service_ops.packet
SET detailed_status = 'Pending - Clinical Review'
WHERE decision_tracking_id IN (
    'b1c2d3e4-5678-4abc-9def-234567890abc',
    'f7b17c23-fbe4-4ed3-b8d9-8e7ef8c44067'
);

-- 5. Reset clinical_decision to PENDING for active decisions
UPDATE service_ops.packet_decision pd
SET 
    clinical_decision = 'PENDING',
    decision_subtype = NULL,
    part_type = NULL,
    decision_outcome = NULL,
    letter_owner = NULL,
    letter_status = NULL,
    letter_medical_docs = NULL,
    esmd_request_status = NULL,
    esmd_request_payload = NULL,
    esmd_attempt_count = NULL,
    esmd_last_sent_at = NULL,
    esmd_request_payload_history = NULL
FROM service_ops.packet p
WHERE pd.packet_id = p.packet_id
AND p.decision_tracking_id IN (
    'b1c2d3e4-5678-4abc-9def-234567890abc',
    'f7b17c23-fbe4-4ed3-b8d9-8e7ef8c44067'
)
AND pd.is_active = true;

-- 6. Reset ClinicalOps watermark to before processing
-- This will allow the processor to pick up new messages
UPDATE service_ops.clinical_ops_poll_watermark
SET 
    last_created_at = '1970-01-01 00:00:00+00'::timestamptz,
    last_message_id = 0,
    updated_at = NOW()
WHERE id = 1;

COMMIT;

