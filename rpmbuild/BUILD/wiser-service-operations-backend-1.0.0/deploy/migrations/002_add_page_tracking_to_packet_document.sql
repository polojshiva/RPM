-- Migration: Add Page Tracking and OCR Metadata to packet_document
-- Purpose: Enable page-level tracking, coversheet detection, and OCR metadata storage
-- Schema: service_ops
-- Date: 2025-01-XX
-- 
-- This migration adds columns to support:
-- - Document splitting into individual pages
-- - Coversheet page detection
-- - Part A/B classification
-- - OCR processing metadata
-- - Processing status tracking

BEGIN;

-- ============================================================================
-- 1. Add page tracking and OCR metadata columns to service_ops.packet_document
-- ============================================================================

-- Document unique identifier: Unique identifier from integration layer (for idempotency)
-- This must be added before migration 003 which creates the unique index
ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS document_unique_identifier VARCHAR(100);

-- Processing path: blob folder path where split outputs are stored
ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS processing_path TEXT;

-- Pages metadata: JSONB structure with page-level information
ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS pages_metadata JSONB;

-- Coversheet page number: which page contains the coversheet (1-indexed)
ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS coversheet_page_number INTEGER;

-- Part type: PART_A, PART_B, or UNKNOWN (app-level enforcement)
ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS part_type VARCHAR(20);

-- OCR metadata: summary of OCR processing (confidence, field counts, etc.)
ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS ocr_metadata JSONB;

-- Split status: tracks document splitting progress
ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS split_status VARCHAR(20) DEFAULT 'NOT_STARTED';

-- OCR status: tracks OCR processing progress
ALTER TABLE service_ops.packet_document
    ADD COLUMN IF NOT EXISTS ocr_status VARCHAR(20) DEFAULT 'NOT_STARTED';

-- ============================================================================
-- 2. Create indexes for performance
-- ============================================================================

-- Index for coversheet page lookups (useful for filtering by coversheet)
CREATE INDEX IF NOT EXISTS idx_packet_document_coversheet_page 
    ON service_ops.packet_document(coversheet_page_number)
    WHERE coversheet_page_number IS NOT NULL;

-- Index for part type filtering (useful for Part A/B queries)
CREATE INDEX IF NOT EXISTS idx_packet_document_part_type 
    ON service_ops.packet_document(part_type)
    WHERE part_type IS NOT NULL;

-- Index for processing status queries (useful for monitoring)
CREATE INDEX IF NOT EXISTS idx_packet_document_split_status 
    ON service_ops.packet_document(split_status)
    WHERE split_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_packet_document_ocr_status 
    ON service_ops.packet_document(ocr_status)
    WHERE ocr_status IS NOT NULL;

-- Composite index for processing workflow queries
CREATE INDEX IF NOT EXISTS idx_packet_document_processing_status 
    ON service_ops.packet_document(split_status, ocr_status)
    WHERE split_status IS NOT NULL OR ocr_status IS NOT NULL;

-- ============================================================================
-- 3. Add column comments for documentation
-- ============================================================================

COMMENT ON COLUMN service_ops.packet_document.document_unique_identifier IS 
    'Unique identifier from integration layer (for idempotency). Used to prevent duplicate document processing within a packet.';

COMMENT ON COLUMN service_ops.packet_document.processing_path IS 
    'Blob storage folder path where split page files are stored. Format: service_ops_processing/{unique_id}/{doc_name}/';

COMMENT ON COLUMN service_ops.packet_document.pages_metadata IS 
    'JSONB structure containing page-level metadata. Structure: {"pages": [{"page_num": 1, "blob_path": "...", "filename": "...", "file_size": 12345, "checksum": "..."}, ...]}';

COMMENT ON COLUMN service_ops.packet_document.coversheet_page_number IS 
    'Page number (1-indexed) containing the coversheet. NULL if not yet detected or no coversheet found.';

COMMENT ON COLUMN service_ops.packet_document.part_type IS 
    'Document part type: PART_A, PART_B, or UNKNOWN. Determined by OCR field analysis or coversheet title.';

COMMENT ON COLUMN service_ops.packet_document.ocr_metadata IS 
    'JSONB structure containing OCR processing metadata: confidence scores, field counts, processing timestamps, etc.';

COMMENT ON COLUMN service_ops.packet_document.split_status IS 
    'Status of document splitting: NOT_STARTED, DONE, or FAILED. Tracks whether document has been split into pages.';

COMMENT ON COLUMN service_ops.packet_document.ocr_status IS 
    'Status of OCR processing: NOT_STARTED, DONE, or FAILED. Tracks whether OCR has been completed for this document.';

-- ============================================================================
-- 4. Update existing rows (set defaults for new columns)
-- ============================================================================

-- Backfill document_unique_identifier for existing rows (if any)
-- Use external_id as fallback, or generate from packet_document_id
UPDATE service_ops.packet_document
SET document_unique_identifier = COALESCE(
    document_unique_identifier,
    external_id,
    'DOC-' || LPAD(packet_document_id::TEXT, 6, '0')
)
WHERE document_unique_identifier IS NULL;

-- Set default status for existing rows (they haven't been processed yet)
UPDATE service_ops.packet_document
SET 
    split_status = COALESCE(split_status, 'NOT_STARTED'),
    ocr_status = COALESCE(ocr_status, 'NOT_STARTED')
WHERE split_status IS NULL OR ocr_status IS NULL;

-- ============================================================================
-- 5. Verify migration (sanity check)
-- ============================================================================

-- Verify columns exist
DO $$
DECLARE
    col_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_schema = 'service_ops'
        AND table_name = 'packet_document'
        AND column_name IN (
            'document_unique_identifier',
            'processing_path',
            'pages_metadata',
            'coversheet_page_number',
            'part_type',
            'ocr_metadata',
            'split_status',
            'ocr_status'
        );
    
    IF col_count < 8 THEN
        RAISE EXCEPTION 'Migration failed: Expected 8 new columns, found %', col_count;
    END IF;
    
    RAISE NOTICE 'Migration successful: All 8 columns added to service_ops.packet_document';
END $$;

COMMIT;

-- ============================================================================
-- Sample pages_metadata JSON structure:
-- ============================================================================
/*
{
  "pages": [
    {
      "page_num": 1,
      "blob_path": "service_ops_processing/unique-123/doc_name/doc_name_page1.pdf",
      "filename": "doc_name_page1.pdf",
      "file_size": 123456,
      "checksum": "sha256:abc123...",
      "thumbnail_url": "https://...",
      "is_coversheet": true,
      "ocr_confidence": 0.95
    },
    {
      "page_num": 2,
      "blob_path": "service_ops_processing/unique-123/doc_name/doc_name_page2.pdf",
      "filename": "doc_name_page2.pdf",
      "file_size": 98765,
      "checksum": "sha256:def456...",
      "thumbnail_url": "https://...",
      "is_coversheet": false,
      "ocr_confidence": null
    }
  ],
  "total_pages": 2,
  "split_completed_at": "2025-01-03T10:30:00Z"
}
*/

-- ============================================================================
-- Sample ocr_metadata JSON structure:
-- ============================================================================
/*
{
  "coversheet_page": 1,
  "overall_confidence": 0.95,
  "fields_extracted": 45,
  "fields_by_page": {
    "1": 45,
    "2": 0
  },
  "part_type": "PART_B",
  "detection_method": "field_count",
  "ocr_engine": "Azure Document Intelligence",
  "model_id": "coversheet-extraction",
  "processed_at": "2025-01-03T10:35:00Z",
  "processing_time_ms": 2500,
  "coversheet_type": "Prior Authorization Request for Wasteful and Inappropriate Service Reduction (WISeR) Model Medicare Part B Fax/Mail Cover Sheet"
}
*/

