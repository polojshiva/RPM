-- Migration 006: Add manual review and audit fields to packet_document
-- Purpose: Support manual editing of OCR extracted fields with full audit trail
-- Date: 2026-01-05

BEGIN;

-- Add updated_extracted_fields column: stores full snapshot of all fields after manual save
ALTER TABLE service_ops.packet_document
ADD COLUMN IF NOT EXISTS updated_extracted_fields JSONB NULL;

COMMENT ON COLUMN service_ops.packet_document.updated_extracted_fields IS 
'Full snapshot of all extracted fields after manual review/update. Contains merged result of OCR + manual edits with metadata (version, last_updated_at, last_updated_by, source).';

-- Add extracted_fields_update_history column: append-only audit trail of all manual updates
ALTER TABLE service_ops.packet_document
ADD COLUMN IF NOT EXISTS extracted_fields_update_history JSONB NULL;

COMMENT ON COLUMN service_ops.packet_document.extracted_fields_update_history IS 
'Append-only array of audit entries tracking every manual update to extracted fields. Each entry contains: updated_at, updated_by, changed_fields (old/new values).';

-- Initialize history as empty array for existing rows (if null)
UPDATE service_ops.packet_document
SET extracted_fields_update_history = '[]'::jsonb
WHERE extracted_fields_update_history IS NULL;

-- Create index on updated_extracted_fields for querying (GIN index for JSONB)
CREATE INDEX IF NOT EXISTS idx_packet_document_updated_extracted_fields 
ON service_ops.packet_document USING GIN (updated_extracted_fields);

-- Create index on extracted_fields_update_history for querying
CREATE INDEX IF NOT EXISTS idx_packet_document_update_history 
ON service_ops.packet_document USING GIN (extracted_fields_update_history);

COMMIT;

-- Verification query (optional - run manually to verify)
-- SELECT 
--     packet_document_id,
--     external_id,
--     CASE 
--         WHEN updated_extracted_fields IS NULL THEN 'No manual updates'
--         ELSE 'Has manual updates'
--     END AS manual_update_status,
--     CASE 
--         WHEN extracted_fields_update_history IS NULL THEN 0
--         ELSE jsonb_array_length(extracted_fields_update_history)
--     END AS update_count
-- FROM service_ops.packet_document
-- ORDER BY packet_document_id DESC
-- LIMIT 10;








