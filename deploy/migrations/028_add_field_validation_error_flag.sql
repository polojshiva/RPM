-- Migration: Add field validation error flag to packet table
-- Purpose: Add has_field_validation_errors boolean flag to track field-level validation errors
-- This flag is used to block ClinicalOps submission and show warnings on UI
-- Date: 2026-01-28

BEGIN;

-- Add has_field_validation_errors column to packet table
ALTER TABLE service_ops.packet
ADD COLUMN IF NOT EXISTS has_field_validation_errors BOOLEAN DEFAULT FALSE NOT NULL;

COMMENT ON COLUMN service_ops.packet.has_field_validation_errors IS 'True if packet has field-level validation errors that need to be fixed before ClinicalOps submission';

-- Create index for efficient querying of packets with validation errors
CREATE INDEX IF NOT EXISTS idx_packet_has_field_validation_errors 
ON service_ops.packet(has_field_validation_errors) 
WHERE has_field_validation_errors = TRUE;

COMMIT;
