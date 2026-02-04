-- Migration: Add clinical_ops_decision_json column to send_serviceops table
-- Purpose: Store Phase 1 clinical decision data from Clinical Ops
-- This column stores the decision JSON written by JSON Generator Phase 1
-- Schema: service_ops
-- Date: 2026-01-29

BEGIN;

-- Add clinical_ops_decision_json column to send_serviceops table
ALTER TABLE service_ops.send_serviceops
ADD COLUMN IF NOT EXISTS clinical_ops_decision_json JSONB;

COMMENT ON COLUMN service_ops.send_serviceops.clinical_ops_decision_json IS 
    'Phase 1: Clinical decision data from Clinical Ops (written by JSON Generator). Contains decision_indicator (A/N), claim_id, decision_status, etc. NULL = not a Phase 1 record.';

-- Create index for faster Phase 1 queries
CREATE INDEX IF NOT EXISTS idx_send_serviceops_clinical_decision 
ON service_ops.send_serviceops(decision_tracking_id, clinical_ops_decision_json)
WHERE clinical_ops_decision_json IS NOT NULL;

COMMENT ON INDEX service_ops.idx_send_serviceops_clinical_decision IS 
    'Index for querying Phase 1 records (clinical_ops_decision_json IS NOT NULL) by decision_tracking_id.';

COMMIT;
