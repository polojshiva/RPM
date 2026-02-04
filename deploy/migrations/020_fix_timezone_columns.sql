-- Migration: Fix Timezone Columns to Use TIMESTAMPTZ
-- Purpose: Ensure all timestamp columns use TIMESTAMPTZ for UTC consistency
-- Schema: service_ops, integration
-- Date: 2026-01-14

BEGIN;

-- ============================================================================
-- Fix service_ops.send_serviceops.created_at (ClinicalOps inbox)
-- ============================================================================
-- Convert TIMESTAMP to TIMESTAMPTZ (assumes existing values are UTC)
ALTER TABLE service_ops.send_serviceops
ALTER COLUMN created_at TYPE TIMESTAMPTZ 
USING created_at AT TIME ZONE 'UTC';

-- ============================================================================
-- Fix service_ops.integration_poll_watermark.last_created_at
-- ============================================================================
-- Convert TIMESTAMP to TIMESTAMPTZ (assumes existing values are UTC)
ALTER TABLE service_ops.integration_poll_watermark
ALTER COLUMN last_created_at TYPE TIMESTAMPTZ 
USING last_created_at AT TIME ZONE 'UTC';

COMMIT;

