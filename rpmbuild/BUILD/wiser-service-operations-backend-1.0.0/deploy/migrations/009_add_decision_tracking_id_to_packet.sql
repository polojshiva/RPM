-- ============================================================================
-- Migration: 009_add_decision_tracking_id_to_packet.sql
-- Purpose: Ensure decision_tracking_id UUID column exists with
--           NOT NULL and UNIQUE constraints for proper idempotency
-- Note: Column may already exist - this migration is idempotent
-- ============================================================================

-- ============================================================================
-- 1. Add decision_tracking_id column (UUID, nullable initially)
-- ============================================================================

ALTER TABLE service_ops.packet 
ADD COLUMN IF NOT EXISTS decision_tracking_id UUID;

DO $$
BEGIN
    RAISE NOTICE '✓ Added decision_tracking_id column to service_ops.packet';
END $$;

-- ============================================================================
-- 2. Add unique constraint (before NOT NULL to allow validation)
-- ============================================================================

-- First, check if there are any existing NULL values that would violate uniqueness
-- (This should be zero since DB is clean, but we check anyway)
DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count
    FROM service_ops.packet
    WHERE decision_tracking_id IS NULL;
    
    IF null_count > 0 THEN
        RAISE NOTICE 'Found % rows with NULL decision_tracking_id (expected for clean DB)', null_count;
    ELSE
        RAISE NOTICE '✓ No NULL values found (clean DB)';
    END IF;
END $$;

-- Add unique constraint (if not exists)
-- This will fail if duplicates exist, which is expected for a clean DB
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'uq_packet_decision_tracking_id'
    ) THEN
        ALTER TABLE service_ops.packet
        ADD CONSTRAINT uq_packet_decision_tracking_id UNIQUE (decision_tracking_id);
        RAISE NOTICE '✓ Added UNIQUE constraint on decision_tracking_id';
    ELSE
        RAISE NOTICE '✓ UNIQUE constraint already exists';
    END IF;
END $$;


-- ============================================================================
-- 3. Ensure NOT NULL constraint (may already be set)
-- ============================================================================

DO $$
BEGIN
    -- Check if column is already NOT NULL
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet'
          AND column_name = 'decision_tracking_id'
          AND is_nullable = 'NO'
    ) THEN
        RAISE NOTICE '✓ decision_tracking_id already has NOT NULL constraint';
    ELSE
        ALTER TABLE service_ops.packet
        ALTER COLUMN decision_tracking_id SET NOT NULL;
        RAISE NOTICE '✓ Set decision_tracking_id to NOT NULL';
    END IF;
END $$;


-- ============================================================================
-- 4. Create index for lookups
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_packet_decision_tracking_id 
ON service_ops.packet(decision_tracking_id);

DO $$
BEGIN
    RAISE NOTICE '✓ Created index on decision_tracking_id';
END $$;

-- ============================================================================
-- 5. Add comment for documentation
-- ============================================================================

COMMENT ON COLUMN service_ops.packet.decision_tracking_id IS 
'Decision tracking ID (UUID) from integration.send_serviceops. Used for idempotency to ensure exactly one packet per decision_tracking_id. Replaces case_id for this purpose.';

DO $$
BEGIN
    RAISE NOTICE '✓ Migration 009 completed successfully';
    RAISE NOTICE '  - decision_tracking_id UUID NOT NULL UNIQUE';
    RAISE NOTICE '  - Index created for lookups';
    RAISE NOTICE '  - Ready for code changes to use this column';
END $$;

