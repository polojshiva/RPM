-- Migration: Create Integration Inbox and Poll Watermark Tables
-- Purpose: Idempotent message processing from integration.send_serviceops
-- Schema: service_ops
-- Date: 2025-01-XX

BEGIN;

-- ============================================================================
-- 1. Create service_ops.integration_inbox table
-- ============================================================================
CREATE TABLE IF NOT EXISTS service_ops.integration_inbox (
    inbox_id BIGSERIAL PRIMARY KEY,
    message_id BIGINT NOT NULL,
    decision_tracking_id UUID NOT NULL,
    message_type VARCHAR(50) NOT NULL,
    source_created_at TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'NEW',
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_by VARCHAR(100),
    locked_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Idempotency constraint: same decision_tracking_id + message_type = same message
    CONSTRAINT uq_integration_inbox_decision_message UNIQUE (decision_tracking_id, message_type)
);

-- ============================================================================
-- 2. Create indexes for performance
-- ============================================================================

-- Index for polling: status + next_attempt_at (for claim queries)
CREATE INDEX IF NOT EXISTS idx_integration_inbox_status_next_attempt 
    ON service_ops.integration_inbox(status, next_attempt_at)
    WHERE status IN ('NEW', 'FAILED');

-- Index for decision_tracking_id lookups
CREATE INDEX IF NOT EXISTS idx_integration_inbox_decision_tracking_id 
    ON service_ops.integration_inbox(decision_tracking_id);

-- Index for message_id lookups (for reconciliation)
CREATE INDEX IF NOT EXISTS idx_integration_inbox_message_id 
    ON service_ops.integration_inbox(message_id);

-- Index for locked jobs (for reclaiming stale locks)
CREATE INDEX IF NOT EXISTS idx_integration_inbox_locked_at 
    ON service_ops.integration_inbox(locked_at)
    WHERE locked_at IS NOT NULL;

-- ============================================================================
-- 3. Create trigger function to auto-update updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION service_ops.update_integration_inbox_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_integration_inbox_updated_at ON service_ops.integration_inbox;
CREATE TRIGGER trg_integration_inbox_updated_at
    BEFORE UPDATE ON service_ops.integration_inbox
    FOR EACH ROW
    EXECUTE FUNCTION service_ops.update_integration_inbox_updated_at();

-- ============================================================================
-- 4. Create service_ops.integration_poll_watermark table
-- ============================================================================
CREATE TABLE IF NOT EXISTS service_ops.integration_poll_watermark (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_created_at TIMESTAMP NOT NULL DEFAULT '1970-01-01 00:00:00',
    last_message_id BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Ensure only one row exists
    CONSTRAINT chk_integration_poll_watermark_single_row CHECK (id = 1)
);

-- ============================================================================
-- 5. Insert initial watermark row if not exists
-- ============================================================================
INSERT INTO service_ops.integration_poll_watermark (id, last_created_at, last_message_id, updated_at)
VALUES (1, '1970-01-01 00:00:00', 0, NOW())
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 6. Add comments for documentation
-- ============================================================================
COMMENT ON TABLE service_ops.integration_inbox IS 
    'Inbox table for idempotent processing of messages from integration.send_serviceops. Tracks processing state, retries, and locks.';

COMMENT ON COLUMN service_ops.integration_inbox.inbox_id IS 
    'Primary key - unique identifier for inbox record';

COMMENT ON COLUMN service_ops.integration_inbox.message_id IS 
    'Foreign reference to integration.send_serviceops.message_id (read-only)';

COMMENT ON COLUMN service_ops.integration_inbox.decision_tracking_id IS 
    'Decision tracking ID from integration table - part of idempotency key';

COMMENT ON COLUMN service_ops.integration_inbox.message_type IS 
    'Message type extracted from payload.message_type - part of idempotency key';

COMMENT ON COLUMN service_ops.integration_inbox.status IS 
    'Processing status: NEW, PROCESSING, DONE, FAILED, DEAD';

COMMENT ON COLUMN service_ops.integration_inbox.attempt_count IS 
    'Number of processing attempts (incremented on each claim)';

COMMENT ON COLUMN service_ops.integration_inbox.next_attempt_at IS 
    'Next time this job can be attempted (used for backoff)';

COMMENT ON COLUMN service_ops.integration_inbox.locked_by IS 
    'Worker ID that currently has this job locked';

COMMENT ON COLUMN service_ops.integration_inbox.locked_at IS 
    'Timestamp when job was locked (used for stale lock detection)';

COMMENT ON COLUMN service_ops.integration_inbox.last_error IS 
    'Last error message if processing failed';

COMMENT ON TABLE service_ops.integration_poll_watermark IS 
    'Watermark table for tracking polling progress. Single row (id=1) stores last processed (created_at, message_id).';

COMMENT ON COLUMN service_ops.integration_poll_watermark.last_created_at IS 
    'Last created_at timestamp from integration.send_serviceops that was processed';

COMMENT ON COLUMN service_ops.integration_poll_watermark.last_message_id IS 
    'Last message_id from integration.send_serviceops that was processed (for tie-breaking)';

COMMIT;

-- ============================================================================
-- Verification queries (run after migration)
-- ============================================================================
-- SELECT * FROM service_ops.integration_inbox LIMIT 1;
-- SELECT * FROM service_ops.integration_poll_watermark;
-- \d service_ops.integration_inbox
-- \d service_ops.integration_poll_watermark

