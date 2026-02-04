-- Migration: Add approved unit of service columns to packet_document
-- Purpose: Add three new columns for approved unit of service 1, 2, 3
-- These are separate from extracted_fields and updated_extracted_fields
-- Date: 2026-01-XX

BEGIN;

-- Add three new columns to packet_document table
ALTER TABLE service_ops.packet_document
ADD COLUMN IF NOT EXISTS approved_unit_of_service_1 VARCHAR(255) NULL,
ADD COLUMN IF NOT EXISTS approved_unit_of_service_2 VARCHAR(255) NULL,
ADD COLUMN IF NOT EXISTS approved_unit_of_service_3 VARCHAR(255) NULL;

COMMENT ON COLUMN service_ops.packet_document.approved_unit_of_service_1 IS 'Approved unit of service 1 - entered manually from UI';
COMMENT ON COLUMN service_ops.packet_document.approved_unit_of_service_2 IS 'Approved unit of service 2 - entered manually from UI';
COMMENT ON COLUMN service_ops.packet_document.approved_unit_of_service_3 IS 'Approved unit of service 3 - entered manually from UI';

COMMIT;
