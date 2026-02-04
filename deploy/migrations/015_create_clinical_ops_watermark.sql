-- Migration: Create ClinicalOps Poll Watermark Table
-- Purpose: Track last processed message_id from service_ops.send_serviceops
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- ============================================================================
-- Create watermark table for ClinicalOps inbox polling
-- ============================================================================
CREATE TABLE IF NOT EXISTS service_ops.clinical_ops_poll_watermark (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_created_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01 00:00:00+00',
    last_message_id BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_single_row CHECK (id = 1)
);

COMMENT ON TABLE service_ops.clinical_ops_poll_watermark IS 
    'Tracks last processed message_id from service_ops.send_serviceops for ClinicalOps inbox polling';

COMMENT ON COLUMN service_ops.clinical_ops_poll_watermark.last_created_at IS 
    'Last processed created_at timestamp from service_ops.send_serviceops';
COMMENT ON COLUMN service_ops.clinical_ops_poll_watermark.last_message_id IS 
    'Last processed message_id from service_ops.send_serviceops';

-- Initialize with default value (UTC epoch)
INSERT INTO service_ops.clinical_ops_poll_watermark (id, last_created_at, last_message_id, updated_at)
VALUES (1, '1970-01-01 00:00:00+00', 0, CURRENT_TIMESTAMP)
ON CONFLICT (id) DO NOTHING;

COMMIT;

