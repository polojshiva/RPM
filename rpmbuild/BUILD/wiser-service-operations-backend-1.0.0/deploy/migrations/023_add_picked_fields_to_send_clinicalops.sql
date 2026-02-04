-- Migration 023: Add is_picked and error_reason columns to send_clinicalops
-- Purpose: Allow ClinicalOps team to mark records as picked/rejected with error reasons
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- Add is_picked column to track if ClinicalOps has reviewed the record
-- NULL = not yet reviewed, TRUE = picked and processed successfully, FALSE = picked but has errors
ALTER TABLE service_ops.send_clinicalops
ADD COLUMN IF NOT EXISTS is_picked BOOLEAN DEFAULT NULL;

-- Add error_reason column to store why a record was rejected
-- Only populated when is_picked = FALSE
ALTER TABLE service_ops.send_clinicalops
ADD COLUMN IF NOT EXISTS error_reason VARCHAR(500) DEFAULT NULL;

-- Add comments for documentation
COMMENT ON COLUMN service_ops.send_clinicalops.is_picked IS 
    'Indicates if ClinicalOps has reviewed this record. NULL = not yet reviewed, TRUE = picked and processed successfully, FALSE = picked but has errors (check error_reason).';

COMMENT ON COLUMN service_ops.send_clinicalops.error_reason IS 
    'Reason why the record was rejected by ClinicalOps (e.g., "Missing HCPCS code", "Invalid provider NPI"). Only populated when is_picked = FALSE.';

-- Create index for faster lookups of unreviewed records
CREATE INDEX IF NOT EXISTS idx_send_clinicalops_is_picked 
ON service_ops.send_clinicalops(is_picked)
WHERE is_picked IS NULL;

COMMENT ON INDEX service_ops.idx_send_clinicalops_is_picked IS 
    'Index for querying unreviewed records (is_picked IS NULL) for ClinicalOps team.';

COMMIT;
