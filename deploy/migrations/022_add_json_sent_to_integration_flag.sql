-- Migration 022: Add json_sent_to_integration flag to send_serviceops
-- Purpose: Track if JSON Generator successfully sent payload to send_integration
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- Add column to track if JSON was sent to integration
-- DEFAULT NULL ensures old records (non-generated payloads) are correctly marked as NULL
ALTER TABLE service_ops.send_serviceops
ADD COLUMN IF NOT EXISTS json_sent_to_integration BOOLEAN DEFAULT NULL;

-- Safety: If column was previously added with DEFAULT FALSE, update old records to NULL
-- This handles the case where migration was run before with incorrect default
-- Note: With DEFAULT NULL, new records will be NULL unless explicitly set by JSON Generator
-- JSON Generator will explicitly set TRUE/FALSE, so any FALSE values should be from JSON Generator
-- We only update FALSE values that existed before send_integration table was created
DO $$
BEGIN
    -- Only run UPDATE if send_integration table exists (migration 018 was run)
    -- This ensures we don't accidentally update legitimate FALSE values from JSON Generator
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'service_ops' AND table_name = 'send_integration'
    ) THEN
        -- Update FALSE values that existed before send_integration table was created
        -- These are old records that should be NULL
        UPDATE service_ops.send_serviceops
        SET json_sent_to_integration = NULL
        WHERE json_sent_to_integration = FALSE
          AND created_at < (
              SELECT MIN(created_at) 
              FROM service_ops.send_integration 
              WHERE created_at IS NOT NULL
          );
    END IF;
END $$;

COMMENT ON COLUMN service_ops.send_serviceops.json_sent_to_integration IS 
    'Indicates if the generated JSON payload was successfully sent to send_integration table. NULL = not a generated payload, TRUE = sent successfully, FALSE = failed to send.';

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_send_serviceops_json_sent 
ON service_ops.send_serviceops(decision_tracking_id, json_sent_to_integration)
WHERE json_sent_to_integration IS NOT NULL;

COMMENT ON INDEX service_ops.idx_send_serviceops_json_sent IS 
    'Index for querying generated payloads by decision_tracking_id and send status.';

COMMIT;

