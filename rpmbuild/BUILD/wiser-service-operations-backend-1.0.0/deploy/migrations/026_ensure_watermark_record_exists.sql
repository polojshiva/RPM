-- Migration 026: Ensure watermark record exists (defensive)
-- Purpose: Defensive migration to ensure integration_poll_watermark has initial record
-- Schema: service_ops
-- Date: 2026-01-23
-- 
-- This is a defensive migration in case migration 001's INSERT failed or was rolled back.
-- The code handles missing watermark gracefully, but this ensures the record exists.

BEGIN;

-- Ensure watermark record exists (idempotent - safe to run multiple times)
INSERT INTO service_ops.integration_poll_watermark (id, last_created_at, last_message_id, updated_at)
VALUES (1, '1970-01-01 00:00:00', 0, NOW())
ON CONFLICT (id) DO NOTHING;

-- Verify record exists
DO $$
DECLARE
    record_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO record_count
    FROM service_ops.integration_poll_watermark
    WHERE id = 1;
    
    IF record_count = 0 THEN
        RAISE EXCEPTION 'Watermark record (id=1) still missing after INSERT. Check table permissions.';
    END IF;
    
    RAISE NOTICE 'Watermark record verified: record exists';
END $$;

COMMIT;
