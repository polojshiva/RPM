-- ============================================================================
-- STAGE 1: UTN Workflow Database Migrations
-- ============================================================================
-- Purpose: Extend database schema for UTN workflow support
--          - Fix idempotency in integration_inbox for UTN events
--          - Add workflow tracking fields to packet_decision
--          - Add resend tracking to integration_receive_serviceops
--
-- Schema: service_ops, integration
-- Date: 2026-01-XX
--
-- IMPORTANT: Run this script in a transaction. Review all changes before committing.
-- ============================================================================

BEGIN;

-- ============================================================================
-- MIGRATION 011: Extend Integration Inbox for UTN Workflow
-- ============================================================================

-- 1. Add message_type_id column to integration_inbox
-- This is critical for routing: we route by message_type_id from source table,
-- not payload.message_type strings (which can drift)
ALTER TABLE service_ops.integration_inbox
ADD COLUMN IF NOT EXISTS message_type_id INTEGER;

COMMENT ON COLUMN service_ops.integration_inbox.message_type_id IS 
    'Message type ID from integration.send_serviceops (1=intake, 2=UTN success, 3=UTN fail). Used for routing, not payload strings.';

-- 2. Add unique constraint on message_id for idempotency
-- message_id is globally unique from integration.send_serviceops and works
-- for all message types (1, 2, 3) without special rules.
-- This allows multiple UTN events (success, fail, retries) per decision_tracking_id.
CREATE UNIQUE INDEX IF NOT EXISTS uq_integration_inbox_message_id 
ON service_ops.integration_inbox(message_id);

COMMENT ON INDEX service_ops.uq_integration_inbox_message_id IS 
    'Idempotency key: prevents duplicate processing of same source message. Works for all message types (intake, UTN success, UTN fail).';

-- 3. Remove old unique constraint that blocks UTN retries
-- The old constraint (decision_tracking_id, message_type) blocks multiple
-- UTN_FAIL attempts for the same decision_tracking_id because they all have
-- message_type = "UTN_FAIL". We now rely on message_id uniqueness instead.
ALTER TABLE service_ops.integration_inbox
DROP CONSTRAINT IF EXISTS uq_integration_inbox_decision_message;

-- 4. Add index on message_type_id for routing queries
CREATE INDEX IF NOT EXISTS idx_integration_inbox_message_type_id 
ON service_ops.integration_inbox(message_type_id)
WHERE message_type_id IS NOT NULL;

COMMENT ON INDEX service_ops.idx_integration_inbox_message_type_id IS 
    'Index for routing queries: filter by message_type_id to route to appropriate handler (1=DocumentProcessor, 2=UtnSuccessHandler, 3=UtnFailHandler).';

-- 5. Update existing rows (if any) to set message_type_id = 1 for backward compatibility
-- Existing rows are all intake messages (message_type_id = 1)
UPDATE service_ops.integration_inbox
SET message_type_id = 1
WHERE message_type_id IS NULL;

-- ============================================================================
-- MIGRATION 012: Extend Packet Decision for UTN Workflow
-- ============================================================================

-- Decision Context Fields
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS decision_subtype TEXT;

COMMENT ON COLUMN service_ops.packet_decision.decision_subtype IS 
    'Decision subtype: DIRECT_PA or STANDARD_PA';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS decision_outcome TEXT;

COMMENT ON COLUMN service_ops.packet_decision.decision_outcome IS 
    'Decision outcome: AFFIRM, NON_AFFIRM, or DISMISSAL';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS part_type TEXT;

COMMENT ON COLUMN service_ops.packet_decision.part_type IS 
    'Medicare Part type: A or B';

-- ESMD Request Tracking Fields
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_request_status TEXT DEFAULT 'NOT_SENT';

COMMENT ON COLUMN service_ops.packet_decision.esmd_request_status IS 
    'ESMD request status: NOT_SENT, SENT, ACKED, FAILED, RESEND_REQUIRED';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_request_payload JSONB;

COMMENT ON COLUMN service_ops.packet_decision.esmd_request_payload IS 
    'Last ESMD decision payload sent to integration.integration_receive_serviceops (JSONB)';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_request_payload_history JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN service_ops.packet_decision.esmd_request_payload_history IS 
    'Array of prior ESMD payloads with hashes, timestamps, and attempt numbers for audit trail';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_attempt_count INTEGER DEFAULT 0;

COMMENT ON COLUMN service_ops.packet_decision.esmd_attempt_count IS 
    'Number of times ESMD payload has been sent (incremented on each resend)';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_last_sent_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.packet_decision.esmd_last_sent_at IS 
    'Timestamp when ESMD payload was last sent to integration.integration_receive_serviceops';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_last_error TEXT;

COMMENT ON COLUMN service_ops.packet_decision.esmd_last_error IS 
    'Last error message if ESMD request failed';

-- UTN Tracking Fields
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn TEXT;

COMMENT ON COLUMN service_ops.packet_decision.utn IS 
    'Unique Tracking Number (UTN) received from ESMD (e.g., "JLB86260080030")';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn_status TEXT DEFAULT 'NONE';

COMMENT ON COLUMN service_ops.packet_decision.utn_status IS 
    'UTN status: NONE, SUCCESS, FAILED';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn_received_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.packet_decision.utn_received_at IS 
    'Timestamp when UTN was received from ESMD (message_type_id = 2)';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn_fail_payload JSONB;

COMMENT ON COLUMN service_ops.packet_decision.utn_fail_payload IS 
    'Full UTN_FAIL payload from integration.send_serviceops (message_type_id = 3) for remediation';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn_action_required TEXT;

COMMENT ON COLUMN service_ops.packet_decision.utn_action_required IS 
    'Action required message from UTN_FAIL payload (shown in UI for remediation)';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS requires_utn_fix BOOLEAN DEFAULT false;

COMMENT ON COLUMN service_ops.packet_decision.requires_utn_fix IS 
    'Flag indicating UTN_FAIL requires user remediation (true = show "Action Required" in UI)';

-- Letter Tracking Fields
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_owner TEXT;

COMMENT ON COLUMN service_ops.packet_decision.letter_owner IS 
    'Letter owner: CLINICAL_OPS (affirm/non-affirm) or SERVICE_OPS (dismissal)';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_status TEXT DEFAULT 'NONE';

COMMENT ON COLUMN service_ops.packet_decision.letter_status IS 
    'Letter status: NONE, PENDING, READY, SENT';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_package JSONB;

COMMENT ON COLUMN service_ops.packet_decision.letter_package IS 
    'Letter package metadata: {filename, blob_path, size, package_id, status_code, etc.}';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_medical_docs JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN service_ops.packet_decision.letter_medical_docs IS 
    'Array of medical document URLs/paths associated with the letter';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_generated_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.packet_decision.letter_generated_at IS 
    'Timestamp when letter was generated (by ClinicalOps or ServiceOps)';

ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_sent_to_integration_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.packet_decision.letter_sent_to_integration_at IS 
    'Timestamp when letter package was forwarded to integration.integration_receive_serviceops';

-- Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_packet_decision_utn_status 
ON service_ops.packet_decision(utn_status)
WHERE utn_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_packet_decision_requires_utn_fix 
ON service_ops.packet_decision(requires_utn_fix)
WHERE requires_utn_fix = true;

CREATE INDEX IF NOT EXISTS idx_packet_decision_esmd_request_status 
ON service_ops.packet_decision(esmd_request_status)
WHERE esmd_request_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_packet_decision_letter_status 
ON service_ops.packet_decision(letter_status)
WHERE letter_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_packet_decision_decision_outcome 
ON service_ops.packet_decision(decision_outcome)
WHERE decision_outcome IS NOT NULL;

-- ============================================================================
-- MIGRATION 013: Extend Integration Receive ServiceOps for UTN Workflow
-- ============================================================================

-- 1. Add correlation_id for tracking resends
-- correlation_id allows tracking multiple requests per decision_tracking_id
-- (e.g., initial send, resend after UTN_FAIL, etc.)
ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS correlation_id UUID DEFAULT gen_random_uuid();

COMMENT ON COLUMN integration.integration_receive_serviceops.correlation_id IS 
    'UUID for tracking resends and correlating multiple requests per decision_tracking_id';

-- 2. Add attempt tracking fields
ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 1;

COMMENT ON COLUMN integration.integration_receive_serviceops.attempt_count IS 
    'Number of attempts (1 = initial send, 2+ = resends after UTN_FAIL)';

ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS resend_of_response_id BIGINT;

COMMENT ON COLUMN integration.integration_receive_serviceops.resend_of_response_id IS 
    'Foreign key to previous response_id if this is a resend (NULL for initial send)';

-- Add foreign key constraint for resend chain
-- Check if constraint exists first (PostgreSQL doesn't support IF NOT EXISTS for constraints)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE table_schema = 'integration' 
        AND table_name = 'integration_receive_serviceops' 
        AND constraint_name = 'fk_irs_resend_of_response_id'
    ) THEN
        ALTER TABLE integration.integration_receive_serviceops
        ADD CONSTRAINT fk_irs_resend_of_response_id 
        FOREIGN KEY (resend_of_response_id) 
        REFERENCES integration.integration_receive_serviceops(response_id)
        ON DELETE SET NULL;
    END IF;
END $$;

-- 3. Add payload versioning fields
ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS payload_hash TEXT;

COMMENT ON COLUMN integration.integration_receive_serviceops.payload_hash IS 
    'SHA-256 hash of payload for audit and deduplication';

ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS payload_version INTEGER DEFAULT 1;

COMMENT ON COLUMN integration.integration_receive_serviceops.payload_version IS 
    'Payload version number (1 = initial, 2+ = updated payload on resend)';

-- 4. Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_irs_correlation_id 
ON integration.integration_receive_serviceops(correlation_id)
WHERE correlation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_irs_resend_of_response_id 
ON integration.integration_receive_serviceops(resend_of_response_id)
WHERE resend_of_response_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_irs_attempt_count 
ON integration.integration_receive_serviceops(attempt_count)
WHERE attempt_count > 1;

CREATE INDEX IF NOT EXISTS idx_irs_decision_attempt 
ON integration.integration_receive_serviceops(decision_tracking_id, attempt_count);

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- Run these queries after migration to verify all changes applied successfully

-- Check integration_inbox changes
SELECT 
    'integration_inbox.message_type_id column' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'integration_inbox' 
            AND column_name = 'message_type_id'
        ) THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status
UNION ALL
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
    END AS status
UNION ALL
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
    END AS status
UNION ALL
-- Check packet_decision changes
SELECT 
    'packet_decision workflow columns (20 total)' AS check_name,
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
    END AS status
UNION ALL
SELECT 
    'packet_decision indexes (5 total)' AS check_name,
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
    END AS status
UNION ALL
-- Check integration_receive_serviceops changes
SELECT 
    'integration_receive_serviceops tracking columns (5 total)' AS check_name,
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
    END AS status
UNION ALL
SELECT 
    'integration_receive_serviceops resend FK constraint' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.table_constraints 
            WHERE table_schema = 'integration' 
            AND table_name = 'integration_receive_serviceops' 
            AND constraint_name = 'fk_irs_resend_of_response_id'
        ) THEN 'PASS' 
        ELSE 'FAIL' 
    END AS status
UNION ALL
SELECT 
    'integration_receive_serviceops indexes (4 total)' AS check_name,
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
-- COMMIT TRANSACTION
-- ============================================================================
-- Review verification results above. If all checks show 'PASS', commit the transaction.
-- If any checks show 'FAIL', rollback and investigate.

-- COMMIT;
-- 
-- If you need to rollback instead:
-- ROLLBACK;

