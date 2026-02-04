-- ============================================================================
-- Validation Query: Verify no duplicate decision_tracking_id values
-- Run this after migration 009 and code deployment
-- ============================================================================

-- Check for duplicate decision_tracking_id values
-- Expected result: 0 rows
SELECT 
    decision_tracking_id,
    COUNT(*) as packet_count,
    STRING_AGG(packet_id::TEXT, ', ' ORDER BY packet_id) as packet_ids,
    STRING_AGG(external_id, ', ' ORDER BY packet_id) as external_ids
FROM service_ops.packet
GROUP BY decision_tracking_id
HAVING COUNT(*) > 1;

-- If any rows are returned, investigate and deduplicate before proceeding

-- Verify all packets have decision_tracking_id set
-- Expected result: 0
SELECT COUNT(*) as null_count
FROM service_ops.packet
WHERE decision_tracking_id IS NULL;

-- Verify case_id is NOT being used to store decision_tracking_id for new packets
-- (This checks if any case_id matches UUID pattern and equals decision_tracking_id)
-- For new packets after migration: Expected 0 rows
SELECT 
    packet_id,
    external_id,
    case_id,
    decision_tracking_id,
    created_at
FROM service_ops.packet
WHERE case_id IS NOT NULL
  AND case_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  AND case_id::uuid = decision_tracking_id
ORDER BY created_at DESC;

