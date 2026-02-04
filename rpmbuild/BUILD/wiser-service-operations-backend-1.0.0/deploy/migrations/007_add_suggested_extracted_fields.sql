-- Migration 007: Add suggested_extracted_fields to packet_document
-- Purpose: Store OCR rerun results without overwriting manual edits in working view
-- Date: 2026-01-05

BEGIN;

-- Add suggested_extracted_fields column: stores latest OCR coversheet result for comparison
ALTER TABLE service_ops.packet_document
ADD COLUMN IF NOT EXISTS suggested_extracted_fields JSONB NULL;

COMMENT ON COLUMN service_ops.packet_document.suggested_extracted_fields IS 
'Latest OCR coversheet result from "Mark as Coversheet" rerun. Used when manual edits exist to preserve working view (extracted_fields) while showing OCR suggestions. Structure: {fields: {...}, coversheet_page_number: N, ocr_run_at: "...", source: "OCR_RERUN_MARK_COVERSHEET"}.';

-- Create index on suggested_extracted_fields for querying (GIN index for JSONB)
CREATE INDEX IF NOT EXISTS idx_packet_document_suggested_extracted_fields 
ON service_ops.packet_document USING GIN (suggested_extracted_fields);

COMMIT;

-- Verification query (optional - run manually to verify)
-- SELECT 
--     packet_document_id,
--     external_id,
--     CASE 
--         WHEN suggested_extracted_fields IS NULL THEN 'No OCR suggestions'
--         ELSE 'Has OCR suggestions'
--     END AS suggestion_status
-- FROM service_ops.packet_document
-- LIMIT 10;








