-- Migration: Update ClinicalOps Poll Watermark to Use Same Strategy as Integration Inbox
-- Purpose: Add last_created_at column and use GREATEST() for reliable watermark updates
-- Schema: service_ops
-- Date: 2026-01-14

BEGIN;

-- ============================================================================
-- Add last_created_at column to clinical_ops_poll_watermark (TIMESTAMPTZ for UTC)
-- ============================================================================
ALTER TABLE service_ops.clinical_ops_poll_watermark
ADD COLUMN IF NOT EXISTS last_created_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01 00:00:00+00';

-- If column already exists as TIMESTAMP (without timezone), convert it
DO $$
BEGIN
    -- Check if column exists and is TIMESTAMP (not TIMESTAMPTZ)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
        AND table_name = 'clinical_ops_poll_watermark' 
        AND column_name = 'last_created_at'
        AND data_type = 'timestamp without time zone'
    ) THEN
        -- Convert TIMESTAMP to TIMESTAMPTZ (assumes existing values are UTC)
        ALTER TABLE service_ops.clinical_ops_poll_watermark
        ALTER COLUMN last_created_at TYPE TIMESTAMPTZ USING last_created_at AT TIME ZONE 'UTC';
    END IF;
END $$;

-- Update existing records to have epoch timestamp if last_created_at is NULL or invalid
UPDATE service_ops.clinical_ops_poll_watermark
SET last_created_at = '1970-01-01 00:00:00+00'
WHERE id = 1 AND (last_created_at IS NULL OR last_created_at < '1970-01-01 00:00:00+00');

-- ============================================================================
-- Update comments
-- ============================================================================
COMMENT ON COLUMN service_ops.clinical_ops_poll_watermark.last_created_at IS 
    'Last processed created_at timestamp from service_ops.send_serviceops (same strategy as integration inbox)';

COMMENT ON COLUMN service_ops.clinical_ops_poll_watermark.last_message_id IS 
    'Last processed message_id from service_ops.send_serviceops (same strategy as integration inbox)';

COMMIT;

