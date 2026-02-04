-- Migration 017: New Workflow Schema - Status, Validation, and Decision Model
-- Purpose: Implement new unified workflow with validation_status, operational_decision, clinical_decision, and audit trails
-- Schema: service_ops
-- Date: 2026-01-XX

BEGIN;

-- ============================================================================
-- 1. Add validation_status to packet table
-- ============================================================================

ALTER TABLE service_ops.packet
ADD COLUMN IF NOT EXISTS validation_status TEXT;

-- Set default for existing rows
UPDATE service_ops.packet
SET validation_status = 'Pending - Validation'
WHERE validation_status IS NULL;

-- Make NOT NULL with default
ALTER TABLE service_ops.packet
ALTER COLUMN validation_status SET DEFAULT 'Pending - Validation',
ALTER COLUMN validation_status SET NOT NULL;

COMMENT ON COLUMN service_ops.packet.validation_status IS 
    'Validation status: Pending - Validation, Validation In Progress, Pending - Manual Review, Validation Updated, Validation Complete, Validation Failed';

-- Add CHECK constraint for validation_status
ALTER TABLE service_ops.packet
DROP CONSTRAINT IF EXISTS check_validation_status;

ALTER TABLE service_ops.packet
ADD CONSTRAINT check_validation_status 
CHECK (validation_status IN (
    'Pending - Validation',
    'Validation In Progress',
    'Pending - Manual Review',
    'Validation Updated',
    'Validation Complete',
    'Validation Failed'
));

-- ============================================================================
-- 2. Update detailed_status to be NOT NULL with default
-- ============================================================================

-- Set default for existing NULL rows
UPDATE service_ops.packet
SET detailed_status = 'Pending - New'
WHERE detailed_status IS NULL;

-- Make NOT NULL with default
ALTER TABLE service_ops.packet
ALTER COLUMN detailed_status SET DEFAULT 'Pending - New',
ALTER COLUMN detailed_status SET NOT NULL;

-- Add CHECK constraint for detailed_status (all new status values)
ALTER TABLE service_ops.packet
DROP CONSTRAINT IF EXISTS check_detailed_status;

ALTER TABLE service_ops.packet
ADD CONSTRAINT check_detailed_status 
CHECK (detailed_status IN (
    'Pending - New',
    'Intake',
    'Validation',
    'Pending - Clinical Review',
    'Clinical Decision Received',
    'Pending - UTN',
    'UTN Received',
    'Generate Decision Letter - Pending',
    'Generate Decision Letter - Complete',
    'Send Decision Letter - Pending',
    'Send Decision Letter - Complete',
    'Decision Complete',
    'Dismissal',
    'Dismissal Complete'
));

-- ============================================================================
-- 3. Add operational_decision and clinical_decision to packet_decision
-- ============================================================================

-- Add operational_decision
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS operational_decision TEXT;

-- Set default for existing rows
UPDATE service_ops.packet_decision
SET operational_decision = 'PENDING'
WHERE operational_decision IS NULL;

-- Make NOT NULL with default
ALTER TABLE service_ops.packet_decision
ALTER COLUMN operational_decision SET DEFAULT 'PENDING',
ALTER COLUMN operational_decision SET NOT NULL;

COMMENT ON COLUMN service_ops.packet_decision.operational_decision IS 
    'Operational decision: PENDING, DISMISSAL, DISMISSAL_COMPLETE, DECISION_COMPLETE';

-- Add CHECK constraint for operational_decision
ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS check_operational_decision;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT check_operational_decision 
CHECK (operational_decision IN ('PENDING', 'DISMISSAL', 'DISMISSAL_COMPLETE', 'DECISION_COMPLETE'));

-- Add clinical_decision
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS clinical_decision TEXT;

-- Set default for existing rows
UPDATE service_ops.packet_decision
SET clinical_decision = 'PENDING'
WHERE clinical_decision IS NULL;

-- Make NOT NULL with default
ALTER TABLE service_ops.packet_decision
ALTER COLUMN clinical_decision SET DEFAULT 'PENDING',
ALTER COLUMN clinical_decision SET NOT NULL;

COMMENT ON COLUMN service_ops.packet_decision.clinical_decision IS 
    'Clinical decision: PENDING, AFFIRM, NON_AFFIRM';

-- Add CHECK constraint for clinical_decision
ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS check_clinical_decision;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT check_clinical_decision 
CHECK (clinical_decision IN ('PENDING', 'AFFIRM', 'NON_AFFIRM'));

-- ============================================================================
-- 4. Add audit trail fields to packet_decision (is_active, supersedes, superseded_by)
-- ============================================================================

-- Add is_active
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- Set default for existing rows
UPDATE service_ops.packet_decision
SET is_active = TRUE
WHERE is_active IS NULL;

-- Make NOT NULL
ALTER TABLE service_ops.packet_decision
ALTER COLUMN is_active SET DEFAULT TRUE,
ALTER COLUMN is_active SET NOT NULL;

COMMENT ON COLUMN service_ops.packet_decision.is_active IS 
    'TRUE for current active decision, FALSE for historical/superseded decisions';

-- Add supersedes (FK to previous decision)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS supersedes BIGINT;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT fk_packet_decision_supersedes 
FOREIGN KEY (supersedes) 
REFERENCES service_ops.packet_decision(packet_decision_id) 
ON DELETE SET NULL;

COMMENT ON COLUMN service_ops.packet_decision.supersedes IS 
    'FK to packet_decision_id that this decision supersedes (for audit trail)';

-- Add superseded_by (FK to next decision)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS superseded_by BIGINT;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT fk_packet_decision_superseded_by 
FOREIGN KEY (superseded_by) 
REFERENCES service_ops.packet_decision(packet_decision_id) 
ON DELETE SET NULL;

COMMENT ON COLUMN service_ops.packet_decision.superseded_by IS 
    'FK to packet_decision_id that supersedes this decision (for audit trail)';

-- Add index for active decisions
CREATE INDEX IF NOT EXISTS idx_packet_decision_active 
ON service_ops.packet_decision(packet_id, is_active) 
WHERE is_active = TRUE;

-- ============================================================================
-- 5. Create packet_validation table for validation audit trail
-- ============================================================================

CREATE TABLE IF NOT EXISTS service_ops.packet_validation (
    packet_validation_id BIGSERIAL PRIMARY KEY,
    packet_id BIGINT NOT NULL REFERENCES service_ops.packet(packet_id) ON DELETE CASCADE,
    packet_document_id BIGINT NOT NULL REFERENCES service_ops.packet_document(packet_document_id) ON DELETE CASCADE,
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'Pending - Validation',
        'Validation In Progress',
        'Pending - Manual Review',
        'Validation Updated',
        'Validation Complete',
        'Validation Failed'
    )),
    validation_type TEXT,  -- 'HETS', 'PECOS', 'FIELD_VALIDATION', 'MANUAL_REVIEW', 'FINAL'
    validation_result JSONB,  -- Validation output data
    validation_errors JSONB,  -- Any errors found
    is_passed BOOLEAN,  -- TRUE if validation passed
    is_active BOOLEAN NOT NULL DEFAULT TRUE,  -- TRUE for current validation state
    supersedes BIGINT REFERENCES service_ops.packet_validation(packet_validation_id) ON DELETE SET NULL,
    superseded_by BIGINT REFERENCES service_ops.packet_validation(packet_validation_id) ON DELETE SET NULL,
    update_reason TEXT,  -- Why validation was updated/corrected
    validated_by TEXT,  -- User who performed/updated validation
    validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE service_ops.packet_validation IS 
    'Audit trail of all validation updates. New record for each validation change.';

COMMENT ON COLUMN service_ops.packet_validation.validation_status IS 
    'Validation status at time of this record';

COMMENT ON COLUMN service_ops.packet_validation.validation_type IS 
    'Type of validation: HETS, PECOS, FIELD_VALIDATION, MANUAL_REVIEW, FINAL';

COMMENT ON COLUMN service_ops.packet_validation.is_active IS 
    'TRUE for current validation state, FALSE for historical';

-- Indexes for packet_validation
CREATE INDEX IF NOT EXISTS idx_packet_validation_packet_active 
ON service_ops.packet_validation(packet_id, is_active) 
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_packet_validation_doc_time 
ON service_ops.packet_validation(packet_document_id, validated_at DESC);

CREATE INDEX IF NOT EXISTS idx_packet_validation_packet_time 
ON service_ops.packet_validation(packet_id, validated_at DESC);

-- ============================================================================
-- 6. Update letter_status CHECK constraint to include new statuses
-- ============================================================================

-- Update letter_status constraint (already handled in migration 016, but ensure it's correct)
ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS check_letter_status;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT check_letter_status 
CHECK (letter_status IS NULL OR letter_status IN ('NONE', 'PENDING', 'READY', 'FAILED', 'SENT'));

COMMIT;

-- ============================================================================
-- Verification Queries
-- ============================================================================

-- Verify packet table changes
DO $$
BEGIN
    ASSERT (SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet' 
            AND column_name = 'validation_status') = 1,
    'validation_status column not found';
    
    ASSERT (SELECT COUNT(*) FROM information_schema.check_constraints 
            WHERE constraint_schema = 'service_ops' 
            AND constraint_name = 'check_validation_status') = 1,
    'check_validation_status constraint not found';
    
    ASSERT (SELECT COUNT(*) FROM information_schema.check_constraints 
            WHERE constraint_schema = 'service_ops' 
            AND constraint_name = 'check_detailed_status') = 1,
    'check_detailed_status constraint not found';
END $$;

-- Verify packet_decision table changes
DO $$
BEGIN
    ASSERT (SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet_decision' 
            AND column_name = 'operational_decision') = 1,
    'operational_decision column not found';
    
    ASSERT (SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet_decision' 
            AND column_name = 'clinical_decision') = 1,
    'clinical_decision column not found';
    
    ASSERT (SELECT COUNT(*) FROM information_schema.columns 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet_decision' 
            AND column_name = 'is_active') = 1,
    'is_active column not found';
    
    ASSERT (SELECT COUNT(*) FROM information_schema.check_constraints 
            WHERE constraint_schema = 'service_ops' 
            AND constraint_name = 'check_operational_decision') = 1,
    'check_operational_decision constraint not found';
    
    ASSERT (SELECT COUNT(*) FROM information_schema.check_constraints 
            WHERE constraint_schema = 'service_ops' 
            AND constraint_name = 'check_clinical_decision') = 1,
    'check_clinical_decision constraint not found';
END $$;

-- Verify packet_validation table exists
DO $$
BEGIN
    ASSERT (SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = 'service_ops' 
            AND table_name = 'packet_validation') = 1,
    'packet_validation table not found';
END $$;

SELECT 'Migration 017 completed successfully' AS status;

