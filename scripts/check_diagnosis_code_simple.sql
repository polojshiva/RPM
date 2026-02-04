-- Simple SQL query to check Diagnosis codes value
-- Run this in your database client (pgAdmin, DBeaver, psql, etc.)

-- BEFORE UPDATE: Run this query
-- AFTER UPDATE: Run this query again and compare

SELECT 
    'BEFORE/AFTER UPDATE CHECK' as check_type,
    external_id,
    -- extracted_fields (working view)
    extracted_fields->'fields'->'Diagnosis codes'->>'value' as diagnosis_value_in_fields,
    extracted_fields->'fields'->'Diagnosis codes'->>'source' as diagnosis_source_in_fields,
    -- updated_extracted_fields (manual review snapshot)
    updated_extracted_fields->'fields'->'Diagnosis codes'->>'value' as diagnosis_value_in_updated,
    updated_extracted_fields->>'last_updated_at' as last_updated_at,
    updated_extracted_fields->>'last_updated_by' as last_updated_by,
    -- history (safe: COALESCE ensures array type)
    jsonb_array_length(COALESCE(extracted_fields_update_history, '[]'::jsonb)) as history_entry_count,
    -- Show all field keys to verify field name (safe: type check in subquery)
    (
        SELECT string_agg(key, ', ' ORDER BY key)
        FROM jsonb_object_keys(
            CASE 
                WHEN jsonb_typeof(extracted_fields->'fields') = 'object'
                THEN extracted_fields->'fields'
                ELSE '{}'::jsonb
            END
        ) key
        WHERE key ILIKE '%diagnosis%' OR key ILIKE '%code%'
    ) as diagnosis_related_keys
FROM service_ops.packet_document
WHERE external_id = 'DOC-3835';




