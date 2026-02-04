-- Migration: Extend Packet Decision for UTN Workflow
-- Purpose: Add workflow tracking fields for ESMD/UTN/letter state
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- ============================================================================
-- 1. Decision Context Fields
-- ============================================================================

-- Decision subtype: DIRECT_PA or STANDARD_PA
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS decision_subtype TEXT;

COMMENT ON COLUMN service_ops.packet_decision.decision_subtype IS 
    'Decision subtype: DIRECT_PA or STANDARD_PA';

-- Decision outcome: AFFIRM, NON_AFFIRM, or DISMISSAL
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS decision_outcome TEXT;

COMMENT ON COLUMN service_ops.packet_decision.decision_outcome IS 
    'Decision outcome: AFFIRM, NON_AFFIRM, or DISMISSAL';

-- Part type: A or B
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS part_type TEXT;

COMMENT ON COLUMN service_ops.packet_decision.part_type IS 
    'Medicare Part type: A or B';

-- ============================================================================
-- 2. ESMD Request Tracking Fields
-- ============================================================================

-- ESMD request status
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_request_status TEXT DEFAULT 'NOT_SENT';

COMMENT ON COLUMN service_ops.packet_decision.esmd_request_status IS 
    'ESMD request status: NOT_SENT, SENT, ACKED, FAILED, RESEND_REQUIRED';

-- Last ESMD payload sent (JSONB for easier querying, but can store as TEXT if needed)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_request_payload JSONB;

COMMENT ON COLUMN service_ops.packet_decision.esmd_request_payload IS 
    'Last ESMD decision payload sent to integration.integration_receive_serviceops (JSONB)';

-- ESMD payload history (array of prior payloads with metadata)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_request_payload_history JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN service_ops.packet_decision.esmd_request_payload_history IS 
    'Array of prior ESMD payloads with hashes, timestamps, and attempt numbers for audit trail';

-- ESMD attempt count
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_attempt_count INTEGER DEFAULT 0;

COMMENT ON COLUMN service_ops.packet_decision.esmd_attempt_count IS 
    'Number of times ESMD payload has been sent (incremented on each resend)';

-- Last ESMD send timestamp
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_last_sent_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.packet_decision.esmd_last_sent_at IS 
    'Timestamp when ESMD payload was last sent to integration.integration_receive_serviceops';

-- Last ESMD error message
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS esmd_last_error TEXT;

COMMENT ON COLUMN service_ops.packet_decision.esmd_last_error IS 
    'Last error message if ESMD request failed';

-- ============================================================================
-- 3. UTN Tracking Fields
-- ============================================================================

-- UTN (Unique Tracking Number)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn TEXT;

COMMENT ON COLUMN service_ops.packet_decision.utn IS 
    'Unique Tracking Number (UTN) received from ESMD (e.g., "JLB86260080030")';

-- UTN status
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn_status TEXT DEFAULT 'NONE';

COMMENT ON COLUMN service_ops.packet_decision.utn_status IS 
    'UTN status: NONE, SUCCESS, FAILED';

-- UTN received timestamp
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn_received_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.packet_decision.utn_received_at IS 
    'Timestamp when UTN was received from ESMD (message_type_id = 2)';

-- UTN failure payload (full JSON from UTN_FAIL message)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn_fail_payload JSONB;

COMMENT ON COLUMN service_ops.packet_decision.utn_fail_payload IS 
    'Full UTN_FAIL payload from integration.send_serviceops (message_type_id = 3) for remediation';

-- UTN action required (extracted from UTN_FAIL payload)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS utn_action_required TEXT;

COMMENT ON COLUMN service_ops.packet_decision.utn_action_required IS 
    'Action required message from UTN_FAIL payload (shown in UI for remediation)';

-- Requires UTN fix flag
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS requires_utn_fix BOOLEAN DEFAULT false;

COMMENT ON COLUMN service_ops.packet_decision.requires_utn_fix IS 
    'Flag indicating UTN_FAIL requires user remediation (true = show "Action Required" in UI)';

-- ============================================================================
-- 4. Letter Tracking Fields
-- ============================================================================

-- Letter owner: CLINICAL_OPS or SERVICE_OPS
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_owner TEXT;

COMMENT ON COLUMN service_ops.packet_decision.letter_owner IS 
    'Letter owner: CLINICAL_OPS (affirm/non-affirm) or SERVICE_OPS (dismissal)';

-- Letter status
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_status TEXT DEFAULT 'NONE';

COMMENT ON COLUMN service_ops.packet_decision.letter_status IS 
    'Letter status: NONE, PENDING, READY, SENT';

-- Letter package metadata (JSONB)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_package JSONB;

COMMENT ON COLUMN service_ops.packet_decision.letter_package IS 
    'Letter package metadata: {filename, blob_path, size, package_id, status_code, etc.}';

-- Letter medical documents (array of doc URLs/paths)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_medical_docs JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN service_ops.packet_decision.letter_medical_docs IS 
    'Array of medical document URLs/paths associated with the letter';

-- Letter generated timestamp
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_generated_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.packet_decision.letter_generated_at IS 
    'Timestamp when letter was generated (by ClinicalOps or ServiceOps)';

-- Letter sent to integration timestamp
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS letter_sent_to_integration_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.packet_decision.letter_sent_to_integration_at IS 
    'Timestamp when letter package was forwarded to integration.integration_receive_serviceops';

-- ============================================================================
-- 5. Add indexes for common queries
-- ============================================================================

-- Index for UTN status queries
CREATE INDEX IF NOT EXISTS idx_packet_decision_utn_status 
ON service_ops.packet_decision(utn_status)
WHERE utn_status IS NOT NULL;

-- Index for requires_utn_fix flag (UI remediation queries)
CREATE INDEX IF NOT EXISTS idx_packet_decision_requires_utn_fix 
ON service_ops.packet_decision(requires_utn_fix)
WHERE requires_utn_fix = true;

-- Index for ESMD request status queries
CREATE INDEX IF NOT EXISTS idx_packet_decision_esmd_request_status 
ON service_ops.packet_decision(esmd_request_status)
WHERE esmd_request_status IS NOT NULL;

-- Index for letter status queries
CREATE INDEX IF NOT EXISTS idx_packet_decision_letter_status 
ON service_ops.packet_decision(letter_status)
WHERE letter_status IS NOT NULL;

-- Index for decision outcome queries
CREATE INDEX IF NOT EXISTS idx_packet_decision_decision_outcome 
ON service_ops.packet_decision(decision_outcome)
WHERE decision_outcome IS NOT NULL;

COMMIT;

-- ============================================================================
-- Verification queries (run manually to verify migration)
-- ============================================================================
-- Check that all new columns exist:
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns 
-- WHERE table_schema = 'service_ops' 
--   AND table_name = 'packet_decision' 
--   AND column_name IN (
--     'decision_subtype', 'decision_outcome', 'part_type',
--     'esmd_request_status', 'esmd_request_payload', 'esmd_request_payload_history',
--     'esmd_attempt_count', 'esmd_last_sent_at', 'esmd_last_error',
--     'utn', 'utn_status', 'utn_received_at', 'utn_fail_payload',
--     'utn_action_required', 'requires_utn_fix',
--     'letter_owner', 'letter_status', 'letter_package', 'letter_medical_docs',
--     'letter_generated_at', 'letter_sent_to_integration_at'
--   );

-- Check that indexes exist:
-- SELECT indexname, indexdef 
-- FROM pg_indexes 
-- WHERE schemaname = 'service_ops' 
--   AND tablename = 'packet_decision' 
--   AND indexname LIKE 'idx_packet_decision_%';

