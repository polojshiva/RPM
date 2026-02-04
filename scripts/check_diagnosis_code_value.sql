-- Script to check the "Diagnosis codes" field value in the database
-- Run this BEFORE and AFTER updating the field in the UI
-- Usage: psql -U <user> -d <database> -f check_diagnosis_code_value.sql

\echo '================================================================================'
\echo 'Checking Diagnosis codes field value for DOC-3835'
\echo '================================================================================'
\echo ''

-- Check extracted_fields (working view)
\echo '=== EXTRACTED_FIELDS (working view) ==='
SELECT 
    external_id,
    packet_id,
    CASE 
        WHEN extracted_fields IS NULL THEN 'NULL'
        WHEN extracted_fields->'fields' IS NULL THEN 'fields key missing'
        WHEN extracted_fields->'fields'->'Diagnosis codes' IS NULL THEN 'Diagnosis codes field missing'
        ELSE 'FOUND'
    END as diagnosis_field_status,
    extracted_fields->'fields'->'Diagnosis codes'->>'value' as diagnosis_value,
    extracted_fields->'fields'->'Diagnosis codes'->>'source' as diagnosis_source,
    extracted_fields->'fields'->'Diagnosis codes'->>'confidence' as diagnosis_confidence,
    jsonb_pretty(extracted_fields->'fields'->'Diagnosis codes') as diagnosis_full_data
FROM service_ops.packet_document
WHERE external_id = 'DOC-3835';

\echo ''
\echo '=== UPDATED_EXTRACTED_FIELDS (manual review snapshot) ==='
SELECT 
    external_id,
    CASE 
        WHEN updated_extracted_fields IS NULL THEN 'NULL'
        WHEN updated_extracted_fields->'fields' IS NULL THEN 'fields key missing'
        WHEN updated_extracted_fields->'fields'->'Diagnosis codes' IS NULL THEN 'Diagnosis codes field missing'
        ELSE 'FOUND'
    END as diagnosis_field_status,
    updated_extracted_fields->'fields'->'Diagnosis codes'->>'value' as diagnosis_value,
    updated_extracted_fields->'fields'->'Diagnosis codes'->>'source' as diagnosis_source,
    updated_extracted_fields->>'last_updated_at' as last_updated_at,
    updated_extracted_fields->>'last_updated_by' as last_updated_by,
    jsonb_pretty(updated_extracted_fields->'fields'->'Diagnosis codes') as diagnosis_full_data
FROM service_ops.packet_document
WHERE external_id = 'DOC-3835';

\echo ''
\echo '=== EXTRACTED_FIELDS_UPDATE_HISTORY (audit trail) ==='
SELECT 
    external_id,
    CASE 
        WHEN extracted_fields_update_history IS NULL THEN 'NULL'
        WHEN jsonb_array_length(extracted_fields_update_history) = 0 THEN 'Empty array'
        ELSE jsonb_array_length(extracted_fields_update_history)::text || ' entries'
    END as history_status,
    jsonb_pretty(extracted_fields_update_history) as full_history
FROM service_ops.packet_document
WHERE external_id = 'DOC-3835';

\echo ''
\echo '=== ALL FIELD KEYS IN EXTRACTED_FIELDS (to see exact field names) ==='
SELECT 
    external_id,
    jsonb_object_keys(extracted_fields->'fields') as field_key
FROM service_ops.packet_document
WHERE external_id = 'DOC-3835'
ORDER BY field_key;

\echo ''
\echo '=== RAW FIELDS (preserved OCR) ==='
SELECT 
    external_id,
    CASE 
        WHEN extracted_fields->'raw'->'fields'->'Diagnosis codes' IS NULL THEN 'NOT FOUND in raw'
        ELSE 'FOUND in raw'
    END as raw_diagnosis_status,
    extracted_fields->'raw'->'fields'->'Diagnosis codes'->>'value' as raw_diagnosis_value
FROM service_ops.packet_document
WHERE external_id = 'DOC-3835';

\echo ''
\echo '================================================================================'
\echo 'Done. Compare the diagnosis_value before and after updating in UI.'
\echo '================================================================================'



