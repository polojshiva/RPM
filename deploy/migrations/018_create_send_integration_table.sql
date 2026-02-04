-- Migration 018: Create service_ops.send_integration table
-- Purpose: ServiceOps → Integration outbox (replaces integration.integration_receive_serviceops)
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- ============================================================================
-- 1. Create service_ops.send_integration table
-- ============================================================================

CREATE TABLE IF NOT EXISTS service_ops.send_integration (
    message_id BIGSERIAL PRIMARY KEY,
    decision_tracking_id UUID NOT NULL,
    workflow_instance_id BIGINT,
    payload JSONB NOT NULL,
    message_status_id INTEGER,
    correlation_id UUID,
    attempt_count INTEGER DEFAULT 1,
    resend_of_message_id BIGINT,
    payload_hash TEXT,
    payload_version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ,
    audit_user VARCHAR(100),
    audit_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT false,
    
    -- Foreign Keys
    CONSTRAINT fk_send_integration_message_status 
        FOREIGN KEY (message_status_id) 
        REFERENCES service_ops.message_status(message_status_id),
    CONSTRAINT fk_send_integration_workflow_instance 
        FOREIGN KEY (workflow_instance_id) 
        REFERENCES service_ops.workflow_instance(workflow_instance_id),
    CONSTRAINT fk_send_integration_resend 
        FOREIGN KEY (resend_of_message_id) 
        REFERENCES service_ops.send_integration(message_id) 
        ON DELETE SET NULL
);

-- ============================================================================
-- 2. Add Comments
-- ============================================================================

COMMENT ON TABLE service_ops.send_integration IS 
    'ServiceOps → Integration outbox. Stores ESMD payloads and letter packages for Integration service to consume.';

COMMENT ON COLUMN service_ops.send_integration.message_id IS 
    'Primary key, auto-incrementing message ID';

COMMENT ON COLUMN service_ops.send_integration.decision_tracking_id IS 
    'UUID linking to service_ops.packet.decision_tracking_id';

COMMENT ON COLUMN service_ops.send_integration.payload IS 
    'JSONB payload containing message_type (ESMD_PAYLOAD or LETTER_PACKAGE) and full message data';

COMMENT ON COLUMN service_ops.send_integration.message_status_id IS 
    'FK to service_ops.message_status. Status: 1=INGESTED, 2=VALIDATED, 3=SENT, 4=ERROR';

COMMENT ON COLUMN service_ops.send_integration.correlation_id IS 
    'UUID for tracking resends and correlating multiple requests per decision_tracking_id';

COMMENT ON COLUMN service_ops.send_integration.attempt_count IS 
    'Number of attempts (1 = initial send, 2+ = resends after UTN_FAIL)';

COMMENT ON COLUMN service_ops.send_integration.resend_of_message_id IS 
    'FK to previous message_id if this is a resend (NULL for initial send)';

COMMENT ON COLUMN service_ops.send_integration.payload_hash IS 
    'SHA-256 hash of payload for audit and deduplication';

COMMENT ON COLUMN service_ops.send_integration.payload_version IS 
    'Payload version number (1 = initial, 2+ = updated payload on resend)';

-- ============================================================================
-- 3. Create Indexes
-- ============================================================================

-- Decision tracking lookup
CREATE INDEX IF NOT EXISTS idx_send_integration_decision_tracking 
    ON service_ops.send_integration(decision_tracking_id);

-- Status filtering
CREATE INDEX IF NOT EXISTS idx_send_integration_message_status 
    ON service_ops.send_integration(message_status_id) 
    WHERE message_status_id IS NOT NULL;

-- Correlation ID (for resend tracking)
CREATE INDEX IF NOT EXISTS idx_send_integration_correlation_id 
    ON service_ops.send_integration(correlation_id) 
    WHERE correlation_id IS NOT NULL;

-- Resend chain
CREATE INDEX IF NOT EXISTS idx_send_integration_resend 
    ON service_ops.send_integration(resend_of_message_id) 
    WHERE resend_of_message_id IS NOT NULL;

-- Attempt count (for retry queries)
CREATE INDEX IF NOT EXISTS idx_send_integration_attempt_count 
    ON service_ops.send_integration(attempt_count) 
    WHERE attempt_count > 1;

-- Composite: decision_tracking_id + attempt_count
CREATE INDEX IF NOT EXISTS idx_send_integration_decision_attempt 
    ON service_ops.send_integration(decision_tracking_id, attempt_count);

-- Created at (for polling)
CREATE INDEX IF NOT EXISTS idx_send_integration_created_at 
    ON service_ops.send_integration(created_at);

-- Payload GIN index (for JSONB queries)
CREATE INDEX IF NOT EXISTS idx_send_integration_payload_gin 
    ON service_ops.send_integration USING GIN (payload);

-- Message type in payload (for filtering)
CREATE INDEX IF NOT EXISTS idx_send_integration_message_type 
    ON service_ops.send_integration((payload->>'message_type')) 
    WHERE payload->>'message_type' IS NOT NULL;

COMMIT;

