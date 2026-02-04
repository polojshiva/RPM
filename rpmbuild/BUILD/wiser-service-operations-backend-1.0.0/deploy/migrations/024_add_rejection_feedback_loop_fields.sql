-- Migration 024: Add rejection feedback loop fields to send_clinicalops
-- Purpose: Enable feedback loop for ClinicalOps rejections back to ServiceOps validation
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- Track if rejected record has been looped back to validation
ALTER TABLE service_ops.send_clinicalops
ADD COLUMN IF NOT EXISTS is_looped_back_to_validation BOOLEAN DEFAULT FALSE;

-- Track retry attempts (prevents infinite retry loops)
ALTER TABLE service_ops.send_clinicalops
ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;

-- Add comments for documentation
COMMENT ON COLUMN service_ops.send_clinicalops.is_looped_back_to_validation IS 
    'Indicates if a rejected record (is_picked = false) has been looped back to ServiceOps validation phase. Prevents reprocessing.';

COMMENT ON COLUMN service_ops.send_clinicalops.retry_count IS 
    'Number of times this decision_tracking_id has been sent to ClinicalOps. Prevents infinite retry loops.';

-- Create index for faster lookups of unprocessed rejections
CREATE INDEX IF NOT EXISTS idx_send_clinicalops_rejected_unprocessed 
ON service_ops.send_clinicalops(is_picked, is_looped_back_to_validation)
WHERE is_picked = FALSE AND is_looped_back_to_validation = FALSE;

COMMENT ON INDEX service_ops.idx_send_clinicalops_rejected_unprocessed IS 
    'Index for querying rejected records that need to be looped back to validation.';

COMMIT;
