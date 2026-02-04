-- Fix duplicate packet_documents before running migration 004
-- This script manually cleans up duplicates by keeping the document with the lowest packet_document_id

-- Step 1: Check for duplicates
SELECT 
    packet_id, 
    COUNT(*) as doc_count,
    array_agg(packet_document_id ORDER BY packet_document_id) as document_ids
FROM service_ops.packet_document
GROUP BY packet_id
HAVING COUNT(*) > 1
ORDER BY packet_id;

-- Step 2: Delete duplicates, keeping the one with lowest packet_document_id
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

-- Step 3: Verify no duplicates remain
SELECT 
    packet_id, 
    COUNT(*) as doc_count
FROM service_ops.packet_document
GROUP BY packet_id
HAVING COUNT(*) > 1;
-- Should return 0 rows

