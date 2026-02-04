-- Migration: Add unique index on document_unique_identifier for idempotency
-- Purpose: Enable idempotent document processing based on document_unique_identifier
-- Schema: service_ops
-- Date: 2025-01-03
-- 
-- NOTE: The document_unique_identifier column already exists in the database.
-- This migration only creates the unique index for idempotency enforcement.
-- 
-- This migration:
-- - Creates unique index on (packet_id, document_unique_identifier) for idempotency
-- - Ensures document_unique_identifier is NOT NULL (after backfill if needed)
-- - Ensures concurrency-safe document processing

BEGIN;

-- ============================================================================
-- 1. Verify document_unique_identifier column exists
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
        AND table_name = 'packet_document' 
        AND column_name = 'document_unique_identifier'
    ) THEN
        RAISE EXCEPTION 'Column document_unique_identifier does not exist. Please add it first.';
    END IF;
    RAISE NOTICE '✓ Column document_unique_identifier exists';
END $$;

-- ============================================================================
-- 2. Backfill NULL values (if any) before making NOT NULL
-- ============================================================================

-- If there are any NULL document_unique_identifier values, we need to handle them
-- For existing records without document_unique_identifier, we'll generate one
-- based on external_id or packet_document_id
DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count
    FROM service_ops.packet_document
    WHERE document_unique_identifier IS NULL;
    
    IF null_count > 0 THEN
        RAISE NOTICE 'Found % rows with NULL document_unique_identifier. Backfilling...', null_count;
        
        -- Generate document_unique_identifier from external_id or packet_document_id
        UPDATE service_ops.packet_document
        SET document_unique_identifier = COALESCE(
            external_id,
            'DOC-' || LPAD(packet_document_id::TEXT, 6, '0')
        )
        WHERE document_unique_identifier IS NULL;
        
        RAISE NOTICE '✓ Backfilled % rows', null_count;
    ELSE
        RAISE NOTICE '✓ No NULL values found';
    END IF;
END $$;

-- ============================================================================
-- 3. Make document_unique_identifier NOT NULL
-- ============================================================================

ALTER TABLE service_ops.packet_document
    ALTER COLUMN document_unique_identifier SET NOT NULL;

DO $$
BEGIN
    RAISE NOTICE '✓ Column document_unique_identifier set to NOT NULL';
END $$;

-- ============================================================================
-- 4. Create unique index for idempotency
-- ============================================================================

-- Unique index on (packet_id, document_unique_identifier)
-- This ensures that within a packet, each document_unique_identifier appears only once
-- Since document_unique_identifier is NOT NULL, we don't need WHERE clause
CREATE UNIQUE INDEX IF NOT EXISTS idx_packet_document_unique_id 
    ON service_ops.packet_document(packet_id, document_unique_identifier);

-- Add comment for documentation
COMMENT ON INDEX service_ops.idx_packet_document_unique_id IS 
    'Unique index ensuring idempotent document processing. Prevents duplicate documents within a packet based on document_unique_identifier.';

-- ============================================================================
-- 5. Verification queries
-- ============================================================================

-- Verify column is NOT NULL
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
        AND table_name = 'packet_document' 
        AND column_name = 'document_unique_identifier'
        AND is_nullable = 'NO'
    ) THEN
        RAISE NOTICE '✓ Column document_unique_identifier is NOT NULL';
    ELSE
        RAISE EXCEPTION '✗ Column document_unique_identifier is still nullable';
    END IF;
END $$;

-- Verify unique index was created
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM pg_indexes 
        WHERE schemaname = 'service_ops' 
        AND tablename = 'packet_document' 
        AND indexname = 'idx_packet_document_unique_id'
    ) THEN
        RAISE NOTICE '✓ Unique index idx_packet_document_unique_id created successfully';
    ELSE
        RAISE EXCEPTION '✗ Unique index idx_packet_document_unique_id was not created';
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- Rollback Script (if needed)
-- ============================================================================
-- To rollback this migration:
-- BEGIN;
-- DROP INDEX IF EXISTS service_ops.idx_packet_document_unique_id;
-- ALTER TABLE service_ops.packet_document ALTER COLUMN document_unique_identifier DROP NOT NULL;
-- COMMIT;
