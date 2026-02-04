-- Migration: Verification Script for UTN Workflow Migrations
-- Purpose: Verify that all migrations (011, 012, 013) applied successfully
-- Schema: service_ops, integration
-- Date: 2026-01-XX

-- ============================================================================
-- Verification: service_ops.integration_inbox
-- ============================================================================

-- Check message_type_id column exists
SELECT 
    'integration_inbox.message_type_id' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'integration_inbox' 
            AND column_name = 'message_type_id'
        ) THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status;

-- Check unique constraint on message_id exists
SELECT 
    'integration_inbox.message_id unique constraint' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM pg_indexes 
            WHERE schemaname = 'service_ops' 
            AND tablename = 'integration_inbox' 
            AND indexname = 'uq_integration_inbox_message_id'
        ) THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status;

-- Check old constraint is removed
SELECT 
    'integration_inbox old constraint removed' AS check_name,
    CASE 
        WHEN NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'integration_inbox' 
            AND constraint_name = 'uq_integration_inbox_decision_message'
        ) THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status;

-- ============================================================================
-- Verification: service_ops.packet_decision
-- ============================================================================

-- Check all new columns exist
SELECT 
    'packet_decision workflow columns' AS check_name,
    CASE 
        WHEN (
            SELECT COUNT(*) FROM information_schema.columns 
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
        ) = 20 THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status;

-- Check indexes exist
SELECT 
    'packet_decision indexes' AS check_name,
    CASE 
        WHEN (
            SELECT COUNT(*) FROM pg_indexes 
            WHERE schemaname = 'service_ops' 
            AND tablename = 'packet_decision' 
            AND indexname IN (
                'idx_packet_decision_utn_status',
                'idx_packet_decision_requires_utn_fix',
                'idx_packet_decision_esmd_request_status',
                'idx_packet_decision_letter_status',
                'idx_packet_decision_decision_outcome'
            )
        ) = 5 THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status;

-- ============================================================================
-- Verification: integration.integration_receive_serviceops
-- ============================================================================

-- Check all new columns exist
SELECT 
    'integration_receive_serviceops tracking columns' AS check_name,
    CASE 
        WHEN (
            SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_schema = 'integration' 
            AND table_name = 'integration_receive_serviceops' 
            AND column_name IN (
                'correlation_id', 'attempt_count', 'resend_of_response_id',
                'payload_hash', 'payload_version'
            )
        ) = 5 THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status;

-- Check foreign key constraint exists
SELECT 
    'integration_receive_serviceops resend FK' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.table_constraints 
            WHERE table_schema = 'integration' 
            AND table_name = 'integration_receive_serviceops' 
            AND constraint_name = 'fk_irs_resend_of_response_id'
        ) THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status;

-- Check indexes exist
SELECT 
    'integration_receive_serviceops indexes' AS check_name,
    CASE 
        WHEN (
            SELECT COUNT(*) FROM pg_indexes 
            WHERE schemaname = 'integration' 
            AND tablename = 'integration_receive_serviceops' 
            AND indexname IN (
                'idx_irs_correlation_id',
                'idx_irs_resend_of_response_id',
                'idx_irs_attempt_count',
                'idx_irs_decision_attempt'
            )
        ) = 4 THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status;

-- ============================================================================
-- Summary Report
-- ============================================================================

SELECT 
    '=== UTN Workflow Migration Verification Summary ===' AS summary;

SELECT 
    'Total checks' AS metric,
    COUNT(*) AS count
FROM (
    SELECT 'integration_inbox.message_type_id' AS check_name UNION ALL
    SELECT 'integration_inbox.message_id unique constraint' UNION ALL
    SELECT 'integration_inbox old constraint removed' UNION ALL
    SELECT 'packet_decision workflow columns' UNION ALL
    SELECT 'packet_decision indexes' UNION ALL
    SELECT 'integration_receive_serviceops tracking columns' UNION ALL
    SELECT 'integration_receive_serviceops resend FK' UNION ALL
    SELECT 'integration_receive_serviceops indexes'
) AS all_checks;

