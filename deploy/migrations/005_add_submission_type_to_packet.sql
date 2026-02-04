-- Migration: Add submission_type column to packet table
-- This field stores the submission type extracted from OCR (Expedited or Standard)

-- ============================================================================
-- 1. Add submission_type column
-- ============================================================================

ALTER TABLE service_ops.packet
    ADD COLUMN IF NOT EXISTS submission_type VARCHAR(50);

COMMENT ON COLUMN service_ops.packet.submission_type IS 
    'Submission type extracted from OCR coversheet: Expedited or Standard';

-- ============================================================================
-- 2. Backfill existing rows (set default to Standard for existing packets)
-- ============================================================================

UPDATE service_ops.packet
SET submission_type = 'Standard'
WHERE submission_type IS NULL;

-- ============================================================================
-- 3. Verification
-- ============================================================================

DO $$
DECLARE
    column_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'service_ops'
        AND table_name = 'packet'
        AND column_name = 'submission_type'
    ) INTO column_exists;
    
    IF column_exists THEN
        RAISE NOTICE '✓ Column submission_type added successfully';
    ELSE
        RAISE EXCEPTION 'Column submission_type was not created';
    END IF;
END $$;

