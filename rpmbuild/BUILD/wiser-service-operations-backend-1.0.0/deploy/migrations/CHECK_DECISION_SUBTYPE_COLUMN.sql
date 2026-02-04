-- ============================================================================
-- CHECK: Verify decision_subtype column exists in packet_decision table
-- ============================================================================
-- Purpose: Check if migration 012 (or STAGE_1_UTN_WORKFLOW_MIGRATIONS) has been applied
-- Schema: service_ops
-- Date: 2026-01-XX
-- ============================================================================

-- Check if decision_subtype column exists
SELECT 
    'decision_subtype column check' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet_decision' 
            AND column_name = 'decision_subtype'
        ) THEN 'PASS - Column exists'
        ELSE 'FAIL - Column does NOT exist (migration not applied)'
    END AS status,
    CASE 
        WHEN EXISTS (
            SELECT 1 
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet_decision' 
            AND column_name = 'decision_subtype'
        ) THEN 'Migration 012 has been applied. Code will work normally.'
        ELSE 'Migration 012 has NOT been applied. Code will use fallback error handling.'
    END AS message;

-- Check all UTN workflow columns (from migration 012)
SELECT 
    'UTN workflow columns check' AS check_name,
    (
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
        AND table_name = 'packet_decision' 
        AND column_name IN (
            'decision_subtype', 'decision_outcome', 'part_type',
            'esmd_request_status', 'esmd_request_payload', 'esmd_request_payload_history',
            'esmd_attempt_count', 'esmd_last_sent_at', 'esmd_last_error',
            'utn', 'utn_status', 'utn_received_at', 'utn_fail_payload',
            'utn_action_required', 'requires_utn_fix',
            'letter_owner', 'letter_status', 'letter_package', 'letter_medical_docs',
            'letter_generated_at', 'letter_sent_to_integration_at'
        )
    ) AS columns_found,
    CASE 
        WHEN (
            SELECT COUNT(*) 
            FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet_decision' 
            AND column_name IN (
                'decision_subtype', 'decision_outcome', 'part_type',
                'esmd_request_status', 'esmd_request_payload', 'esmd_request_payload_history',
                'esmd_attempt_count', 'esmd_last_sent_at', 'esmd_last_error',
                'utn', 'utn_status', 'utn_received_at', 'utn_fail_payload',
                'utn_action_required', 'requires_utn_fix',
                'letter_owner', 'letter_status', 'letter_package', 'letter_medical_docs',
                'letter_generated_at', 'letter_sent_to_integration_at'
            )
        ) = 20 THEN 'PASS - All 20 UTN workflow columns exist'
        ELSE 'FAIL - Some columns missing (migration incomplete)'
    END AS status;

-- Detailed column list
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_schema = 'service_ops' 
AND table_name = 'packet_decision' 
AND column_name IN (
    'decision_subtype', 'decision_outcome', 'part_type',
    'esmd_request_status', 'esmd_request_payload', 'esmd_request_payload_history',
    'esmd_attempt_count', 'esmd_last_sent_at', 'esmd_last_error',
    'utn', 'utn_status', 'utn_received_at', 'utn_fail_payload',
    'utn_action_required', 'requires_utn_fix',
    'letter_owner', 'letter_status', 'letter_package', 'letter_medical_docs',
    'letter_generated_at', 'letter_sent_to_integration_at'
)
ORDER BY column_name;
