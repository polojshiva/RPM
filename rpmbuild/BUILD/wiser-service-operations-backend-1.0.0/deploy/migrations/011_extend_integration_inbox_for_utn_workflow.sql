-- Migration: Extend Integration Inbox for UTN Workflow
-- Purpose: Add message_type_id for routing and fix idempotency for UTN events
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- ============================================================================
-- 1. Add message_type_id column to integration_inbox
-- ============================================================================
-- This is critical for routing: we route by message_type_id from source table,
-- not payload.message_type strings (which can drift)
ALTER TABLE service_ops.integration_inbox
ADD COLUMN IF NOT EXISTS message_type_id INTEGER;

COMMENT ON COLUMN service_ops.integration_inbox.message_type_id IS 
    'Message type ID from integration.send_serviceops (1=intake, 2=UTN success, 3=UTN fail). Used for routing, not payload strings.';

-- ============================================================================
-- 2. Add unique constraint on message_id for idempotency
-- ============================================================================
-- message_id is globally unique from integration.send_serviceops and works
-- for all message types (1, 2, 3) without special rules.
-- This allows multiple UTN events (success, fail, retries) per decision_tracking_id.
CREATE UNIQUE INDEX IF NOT EXISTS uq_integration_inbox_message_id 
ON service_ops.integration_inbox(message_id);

COMMENT ON INDEX service_ops.uq_integration_inbox_message_id IS 
    'Idempotency key: prevents duplicate processing of same source message. Works for all message types (intake, UTN success, UTN fail).';

-- ============================================================================
-- 3. Remove old unique constraint that blocks UTN retries
-- ============================================================================
-- The old constraint (decision_tracking_id, message_type) blocks multiple
-- UTN_FAIL attempts for the same decision_tracking_id because they all have
-- message_type = "UTN_FAIL". We now rely on message_id uniqueness instead.
ALTER TABLE service_ops.integration_inbox
DROP CONSTRAINT IF EXISTS uq_integration_inbox_decision_message;

-- ============================================================================
-- 4. Add index on message_type_id for routing queries
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_integration_inbox_message_type_id 
ON service_ops.integration_inbox(message_type_id)
WHERE message_type_id IS NOT NULL;

COMMENT ON INDEX service_ops.idx_integration_inbox_message_type_id IS 
    'Index for routing queries: filter by message_type_id to route to appropriate handler (1=DocumentProcessor, 2=UtnSuccessHandler, 3=UtnFailHandler).';

-- ============================================================================
-- 5. Update existing rows (if any) to set message_type_id = 1 for backward compatibility
-- ============================================================================
-- Existing rows are all intake messages (message_type_id = 1)
UPDATE service_ops.integration_inbox
SET message_type_id = 1
WHERE message_type_id IS NULL;

COMMIT;

-- ============================================================================
-- Verification queries (run manually to verify migration)
-- ============================================================================
-- Check that message_type_id column exists:
-- SELECT column_name, data_type, is_nullable 
-- FROM information_schema.columns 
-- WHERE table_schema = 'service_ops' 
--   AND table_name = 'integration_inbox' 
--   AND column_name = 'message_type_id';

-- Check that unique constraint on message_id exists:
-- SELECT indexname, indexdef 
-- FROM pg_indexes 
-- WHERE schemaname = 'service_ops' 
--   AND tablename = 'integration_inbox' 
--   AND indexname = 'uq_integration_inbox_message_id';

-- Check that old constraint is removed:
-- SELECT constraint_name 
-- FROM information_schema.table_constraints 
-- WHERE table_schema = 'service_ops' 
--   AND table_name = 'integration_inbox' 
--   AND constraint_name = 'uq_integration_inbox_decision_message';
-- Should return 0 rows

