-- Migration: Enforce single consolidated document per packet
-- Purpose: Support consolidated document workflow (1 packet -> 1 document)
-- Schema: service_ops
-- Date: 2026-01-04
-- 
-- This migration:
-- - Adds consolidated_blob_path column to store consolidated PDF path
-- - Adds UNIQUE constraint on packet_id to enforce exactly one packet_document per packet
-- - Drops old unique index on (packet_id, document_unique_identifier) if it exists
-- - Creates new unique index on packet_id only

BEGIN;

-- ============================================================================
-- 1. Add consolidated_blob_path column
-- ============================================================================

ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS consolidated_blob_path TEXT;

COMMENT ON COLUMN service_ops.packet_document.consolidated_blob_path IS 
    'Blob storage path to the consolidated PDF file (merged from all input documents)';

DO $$
BEGIN
    RAISE NOTICE '✓ Added consolidated_blob_path column';
END $$;

-- ============================================================================
-- 2. Drop old unique index on (packet_id, document_unique_identifier) if exists
-- ============================================================================

DROP INDEX IF EXISTS service_ops.idx_packet_document_unique_id;

DO $$
BEGIN
    RAISE NOTICE '✓ Dropped old unique index on (packet_id, document_unique_identifier)';
END $$;

-- ============================================================================
-- 3. Handle existing duplicate packet_documents (if any)
-- ============================================================================

-- For packets with multiple documents, keep only the first one (by packet_document_id)
-- This is a one-time cleanup before enforcing the constraint
DO $$
DECLARE
    duplicate_count INTEGER;
    deleted_count INTEGER;
BEGIN
    -- Count packets with multiple documents
    SELECT COUNT(DISTINCT packet_id) INTO duplicate_count
    FROM (
        SELECT packet_id, COUNT(*) as doc_count
        FROM service_ops.packet_document
        GROUP BY packet_id
        HAVING COUNT(*) > 1
    ) duplicates;
    
    IF duplicate_count > 0 THEN
        RAISE NOTICE 'Found % packets with multiple documents. Keeping first document per packet...', duplicate_count;
        
        -- Delete duplicates, keeping the one with lowest packet_document_id (first created)
        -- Use a more robust approach: delete all except the one with minimum packet_document_id per packet_id
        WITH keep_docs AS (
            SELECT MIN(packet_document_id) as keep_id, packet_id
            FROM service_ops.packet_document
            GROUP BY packet_id
        )
        DELETE FROM service_ops.packet_document pd
        WHERE EXISTS (
            SELECT 1
            FROM keep_docs kd
            WHERE kd.packet_id = pd.packet_id
            AND kd.keep_id != pd.packet_document_id
        );
        
        GET DIAGNOSTICS deleted_count = ROW_COUNT;
        RAISE NOTICE '✓ Cleaned up % duplicate documents', deleted_count;
    ELSE
        RAISE NOTICE '✓ No duplicate documents found';
    END IF;
END $$;

-- ============================================================================
-- 4. Verify no duplicates exist before creating index
-- ============================================================================

DO $$
DECLARE
    remaining_duplicates INTEGER;
BEGIN
    -- Check if any duplicates still exist
    SELECT COUNT(*) INTO remaining_duplicates
    FROM (
        SELECT packet_id, COUNT(*) as doc_count
        FROM service_ops.packet_document
        GROUP BY packet_id
        HAVING COUNT(*) > 1
    ) duplicates;
    
    IF remaining_duplicates > 0 THEN
        RAISE EXCEPTION 'Cannot create unique index: % packets still have multiple documents. Please clean up duplicates manually.', remaining_duplicates;
    END IF;
    
    RAISE NOTICE '✓ Verified no duplicates exist';
END $$;

-- ============================================================================
-- 5. Create UNIQUE constraint on packet_id
-- ============================================================================

-- Create unique index on packet_id to enforce exactly one document per packet
CREATE UNIQUE INDEX IF NOT EXISTS idx_packet_document_packet_id_unique
    ON service_ops.packet_document(packet_id);

COMMENT ON INDEX service_ops.idx_packet_document_packet_id_unique IS 
    'Unique index ensuring exactly one packet_document per packet_id (consolidated document workflow)';

DO $$
BEGIN
    RAISE NOTICE '✓ Created unique index on packet_id';
END $$;

-- ============================================================================
-- 6. Verification
-- ============================================================================

DO $$
DECLARE
    index_exists BOOLEAN;
    column_exists BOOLEAN;
BEGIN
    -- Check if index exists
    SELECT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'service_ops'
        AND tablename = 'packet_document'
        AND indexname = 'idx_packet_document_packet_id_unique'
    ) INTO index_exists;
    
    -- Check if column exists
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'service_ops'
        AND table_name = 'packet_document'
        AND column_name = 'consolidated_blob_path'
    ) INTO column_exists;
    
    IF NOT index_exists THEN
        RAISE EXCEPTION 'Unique index on packet_id was not created';
    END IF;
    
    IF NOT column_exists THEN
        RAISE EXCEPTION 'consolidated_blob_path column was not created';
    END IF;
    
    RAISE NOTICE '✓ Migration 004 completed successfully';
    RAISE NOTICE '  - consolidated_blob_path column: %', column_exists;
    RAISE NOTICE '  - Unique index on packet_id: %', index_exists;
END $$;

COMMIT;

