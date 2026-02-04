-- Verification Script for Migration 002
-- Run this after executing 002_add_page_tracking_to_packet_document.sql
-- Purpose: Verify all columns, indexes, and defaults are correctly applied

-- ============================================================================
-- 1. Verify all 7 columns exist
-- ============================================================================
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'service_ops'
    AND table_name = 'packet_document'
    AND column_name IN (
        'processing_path',
        'pages_metadata',
        'coversheet_page_number',
        'part_type',
        'ocr_metadata',
        'split_status',
        'ocr_status'
    )
ORDER BY column_name;

-- Expected: 7 rows

-- ============================================================================
-- 2. Verify indexes exist
-- ============================================================================
SELECT 
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'service_ops'
    AND tablename = 'packet_document'
    AND indexname LIKE 'idx_packet_document_%'
ORDER BY indexname;

-- Expected: 5 indexes
-- - idx_packet_document_coversheet_page
-- - idx_packet_document_part_type
-- - idx_packet_document_split_status
-- - idx_packet_document_ocr_status
-- - idx_packet_document_processing_status

-- ============================================================================
-- 3. Verify column comments exist
-- ============================================================================
SELECT 
    column_name,
    col_description(
        (SELECT oid FROM pg_class WHERE relname = 'packet_document' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'service_ops')),
        ordinal_position
    ) as column_comment
FROM information_schema.columns
WHERE table_schema = 'service_ops'
    AND table_name = 'packet_document'
    AND column_name IN (
        'processing_path',
        'pages_metadata',
        'coversheet_page_number',
        'part_type',
        'ocr_metadata',
        'split_status',
        'ocr_status'
    )
ORDER BY column_name;

-- Expected: All 7 columns should have comments

-- ============================================================================
-- 4. Test insert with new columns (backward compatibility)
-- ============================================================================
-- This should work without specifying new columns
DO $$
DECLARE
    test_packet_id BIGINT;
    test_doc_id BIGINT;
BEGIN
    -- Get or create a test packet
    SELECT packet_id INTO test_packet_id
    FROM service_ops.packet
    LIMIT 1;
    
    IF test_packet_id IS NULL THEN
        -- Create a test packet if none exists
        INSERT INTO service_ops.packet (
            external_id, beneficiary_name, beneficiary_mbi,
            provider_name, provider_npi, service_type,
            received_date, due_date
        ) VALUES (
            'PKT-TEST-001', 'Test Patient', 'MBI123456',
            'Test Provider', '1234567890', 'Test Service',
            NOW(), NOW()
        ) RETURNING packet_id INTO test_packet_id;
    END IF;
    
    -- Test insert without new columns (backward compatibility)
    INSERT INTO service_ops.packet_document (
        external_id,
        packet_id,
        file_name,
        document_type_id,
        uploaded_at
    ) VALUES (
        'DOC-TEST-001',
        test_packet_id,
        'test_document.pdf',
        1,  -- Assuming document_type_id = 1 exists
        NOW()
    ) RETURNING packet_document_id INTO test_doc_id;
    
    RAISE NOTICE '✓ Backward compatibility test passed: Inserted document_id = %', test_doc_id;
    
    -- Test update with new columns
    UPDATE service_ops.packet_document
    SET 
        processing_path = 'service_ops_processing/test-123/test_document/',
        split_status = 'DONE',
        coversheet_page_number = 1,
        part_type = 'PART_B'
    WHERE packet_document_id = test_doc_id;
    
    RAISE NOTICE '✓ New columns update test passed';
    
    -- Clean up test data (optional - comment out if you want to keep it)
    -- DELETE FROM service_ops.packet_document WHERE packet_document_id = test_doc_id;
    -- RAISE NOTICE '✓ Test data cleaned up';
    
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE '✗ Test failed: %', SQLERRM;
        RAISE;
END $$;

-- ============================================================================
-- 5. Test JSONB columns with sample data
-- ============================================================================
DO $$
DECLARE
    test_doc_id BIGINT;
BEGIN
    -- Get a test document
    SELECT packet_document_id INTO test_doc_id
    FROM service_ops.packet_document
    WHERE external_id = 'DOC-TEST-001'
    LIMIT 1;
    
    IF test_doc_id IS NOT NULL THEN
        -- Test pages_metadata JSONB
        UPDATE service_ops.packet_document
        SET pages_metadata = '{
            "pages": [
                {
                    "page_num": 1,
                    "blob_path": "service_ops_processing/test-123/test_document/test_document_page1.pdf",
                    "filename": "test_document_page1.pdf",
                    "file_size": 123456,
                    "checksum": "sha256:test123",
                    "is_coversheet": true
                }
            ],
            "total_pages": 1,
            "split_completed_at": "2025-01-03T10:30:00Z"
        }'::jsonb
        WHERE packet_document_id = test_doc_id;
        
        -- Test ocr_metadata JSONB
        UPDATE service_ops.packet_document
        SET ocr_metadata = '{
            "coversheet_page": 1,
            "overall_confidence": 0.95,
            "fields_extracted": 45,
            "part_type": "PART_B",
            "processed_at": "2025-01-03T10:35:00Z"
        }'::jsonb
        WHERE packet_document_id = test_doc_id;
        
        RAISE NOTICE '✓ JSONB columns test passed';
    ELSE
        RAISE NOTICE '⚠ Skipping JSONB test: No test document found';
    END IF;
END $$;

-- ============================================================================
-- 6. Summary report
-- ============================================================================
SELECT 
    'Migration 002 Verification Summary' as report_section,
    COUNT(*) FILTER (WHERE column_name IN ('processing_path', 'pages_metadata', 'coversheet_page_number', 'part_type', 'ocr_metadata', 'split_status', 'ocr_status')) as columns_found,
    (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'service_ops' AND tablename = 'packet_document' AND indexname LIKE 'idx_packet_document_%') as indexes_found,
    CASE 
        WHEN COUNT(*) FILTER (WHERE column_name IN ('processing_path', 'pages_metadata', 'coversheet_page_number', 'part_type', 'ocr_metadata', 'split_status', 'ocr_status')) = 7 
            AND (SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'service_ops' AND tablename = 'packet_document' AND indexname LIKE 'idx_packet_document_%') = 5
        THEN '✓ Migration 002 successful'
        ELSE '✗ Migration 002 incomplete - check above results'
    END as status
FROM information_schema.columns
WHERE table_schema = 'service_ops'
    AND table_name = 'packet_document';

