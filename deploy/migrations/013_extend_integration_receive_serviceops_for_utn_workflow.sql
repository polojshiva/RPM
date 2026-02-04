-- Migration: Extend Integration Receive ServiceOps for UTN Workflow
-- Purpose: Add correlation_id, attempt tracking, and payload versioning for resends
-- Schema: integration
-- Date: 2026-01-XX

BEGIN;

-- ============================================================================
-- 1. Add correlation_id for tracking resends
-- ============================================================================
-- correlation_id allows tracking multiple requests per decision_tracking_id
-- (e.g., initial send, resend after UTN_FAIL, etc.)
ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS correlation_id UUID DEFAULT gen_random_uuid();

COMMENT ON COLUMN integration.integration_receive_serviceops.correlation_id IS 
    'UUID for tracking resends and correlating multiple requests per decision_tracking_id';

-- ============================================================================
-- 2. Add attempt tracking fields
-- ============================================================================

-- Attempt count (incremented on each resend)
ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 1;

COMMENT ON COLUMN integration.integration_receive_serviceops.attempt_count IS 
    'Number of attempts (1 = initial send, 2+ = resends after UTN_FAIL)';

-- Link to previous response_id (for resend chain)
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

-- ============================================================================
-- 3. Add payload versioning fields
-- ============================================================================

-- Payload hash (for audit and deduplication)
ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS payload_hash TEXT;

COMMENT ON COLUMN integration.integration_receive_serviceops.payload_hash IS 
    'SHA-256 hash of payload for audit and deduplication';

-- Payload version (incremented on each resend with different payload)
ALTER TABLE integration.integration_receive_serviceops
ADD COLUMN IF NOT EXISTS payload_version INTEGER DEFAULT 1;

COMMENT ON COLUMN integration.integration_receive_serviceops.payload_version IS 
    'Payload version number (1 = initial, 2+ = updated payload on resend)';

-- ============================================================================
-- 4. Add indexes for common queries
-- ============================================================================

-- Index for correlation_id lookups
CREATE INDEX IF NOT EXISTS idx_irs_correlation_id 
ON integration.integration_receive_serviceops(correlation_id)
WHERE correlation_id IS NOT NULL;

-- Index for resend chain queries
CREATE INDEX IF NOT EXISTS idx_irs_resend_of_response_id 
ON integration.integration_receive_serviceops(resend_of_response_id)
WHERE resend_of_response_id IS NOT NULL;

-- Index for attempt_count queries (find retries)
CREATE INDEX IF NOT EXISTS idx_irs_attempt_count 
ON integration.integration_receive_serviceops(attempt_count)
WHERE attempt_count > 1;

-- Composite index for decision_tracking_id + attempt_count
CREATE INDEX IF NOT EXISTS idx_irs_decision_attempt 
ON integration.integration_receive_serviceops(decision_tracking_id, attempt_count);

COMMIT;

-- ============================================================================
-- Verification queries (run manually to verify migration)
-- ============================================================================
-- Check that all new columns exist:
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns 
-- WHERE table_schema = 'integration' 
--   AND table_name = 'integration_receive_serviceops' 
--   AND column_name IN (
--     'correlation_id', 'attempt_count', 'resend_of_response_id',
--     'payload_hash', 'payload_version'
--   );

-- Check that foreign key constraint exists:
-- SELECT constraint_name, constraint_type
-- FROM information_schema.table_constraints 
-- WHERE table_schema = 'integration' 
--   AND table_name = 'integration_receive_serviceops' 
--   AND constraint_name = 'fk_irs_resend_of_response_id';

-- Check that indexes exist:
-- SELECT indexname, indexdef 
-- FROM pg_indexes 
-- WHERE schemaname = 'integration' 
--   AND tablename = 'integration_receive_serviceops' 
--   AND indexname LIKE 'idx_irs_%';

