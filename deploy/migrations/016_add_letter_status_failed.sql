-- Migration: Add FAILED status support for letter_status
-- Purpose: Support FAILED status for letter generation failures
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- Update comment to include FAILED
COMMENT ON COLUMN service_ops.packet_decision.letter_status IS 
    'Letter status: NONE, PENDING, READY, FAILED, SENT';

-- Add check constraint to enforce valid values
ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS check_letter_status;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT check_letter_status 
CHECK (letter_status IS NULL OR letter_status IN ('NONE', 'PENDING', 'READY', 'FAILED', 'SENT'));

COMMIT;

