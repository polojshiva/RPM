-- Migration: Add clinical_decision_applied_at column to send_serviceops table
-- Purpose: Track when a clinical decision from clinical_ops_decision_json has been successfully applied to packet_decision
-- This enables reliable retry logic and prevents watermark from skipping failed messages
-- Schema: service_ops
-- Date: 2026-02-02

BEGIN;

-- Add clinical_decision_applied_at column to send_serviceops table
ALTER TABLE service_ops.send_serviceops
ADD COLUMN IF NOT EXISTS clinical_decision_applied_at TIMESTAMPTZ;

COMMENT ON COLUMN service_ops.send_serviceops.clinical_decision_applied_at IS 
    'Timestamp when the clinical decision from clinical_ops_decision_json was successfully written to packet_decision. NULL = decision not yet applied (will be retried). Set after successful commit of decision update.';

-- Create index for faster queries on unapplied decisions
CREATE INDEX IF NOT EXISTS idx_send_serviceops_clinical_decision_applied 
ON service_ops.send_serviceops(clinical_decision_applied_at, created_at, message_id)
WHERE clinical_ops_decision_json IS NOT NULL 
  AND clinical_decision_applied_at IS NULL;

COMMENT ON INDEX service_ops.idx_send_serviceops_clinical_decision_applied IS 
    'Index for querying unapplied clinical decisions (clinical_ops_decision_json IS NOT NULL AND clinical_decision_applied_at IS NULL).';

-- Backfill: Set clinical_decision_applied_at for rows that already have json_sent_to_integration = true
-- These are Phase 2 rows that likely already had their decision applied in Phase 1
-- However, we cannot be 100% certain, so we set it to a safe default (created_at) for Phase 2 rows
-- Phase 1 rows (json_sent_to_integration IS NULL or false) will remain NULL and be processed
UPDATE service_ops.send_serviceops
SET clinical_decision_applied_at = created_at
WHERE clinical_ops_decision_json IS NOT NULL
  AND json_sent_to_integration = true
  AND clinical_decision_applied_at IS NULL;

COMMENT ON COLUMN service_ops.send_serviceops.clinical_decision_applied_at IS 
    'Timestamp when the clinical decision from clinical_ops_decision_json was successfully written to packet_decision. NULL = decision not yet applied (will be retried). Set after successful commit of decision update.';

COMMIT;
